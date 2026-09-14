"""Execute a bounded batch of ready tool steps.

Independent read-only steps may run concurrently. Steps with dependencies or
side effects stay single-filed so the plan remains deterministic.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import time

from ..contracts.plan import AgentPlan, PlanStep
from ..contracts.tool import ToolCallProposal, ToolResultEnvelope
from ..verifier import verify_plan
from ..tools.base import ToolContext, ToolError
from ..security import permissions_for_run
from . import _append_event, safe_tool_payload


def _ready_steps(plan: AgentPlan) -> list[PlanStep]:
    completed = {step.id for step in plan.steps if step.status == "SUCCEEDED"}
    return [step for step in plan.steps if step.status in ("PENDING", "READY") and set(step.depends_on).issubset(completed)]


def _arguments(step: PlanStep, state: dict) -> dict:
    arguments = dict(step.input_bindings)
    for key, value in list(arguments.items()):
        if value == "$goal":
            arguments[key] = state.get("normalized_question") or state.get("question") or ""
    return arguments


def _context(state: dict, ctx, plan: AgentPlan) -> ToolContext:
    return ToolContext(
        user_id=str(state.get("user_id") or ""), run_id=state.get("run_id"), plan_id=plan.id,
        session_factory=ctx.session_factory,
        services={"retrieval_service_factory": ctx.retrieval_service_factory},
        permissions=permissions_for_run(write_tools_enabled=ctx.settings.agent_write_tools_enabled),
    )


def _execute_one(ctx, proposal: ToolCallProposal, context: ToolContext, confirmed: bool):
    started = time.monotonic()
    result = ctx.tool_executor.execute(proposal, context, confirmed=confirmed)
    return result, round((time.monotonic() - started) * 1000, 3)


def _emit_completed(ctx, answer_id: str, step: PlanStep, proposal: ToolCallProposal, result: ToolResultEnvelope, duration_ms: float) -> None:
    _append_event(ctx, answer_id, {
        "type": "tool.completed" if result.status == "SUCCEEDED" else "tool.failed",
        "call_id": proposal.call_id, "tool": proposal.tool_name, "step_id": step.id,
        "message": result.summary, "duration_ms": duration_ms, "status": result.status,
        "output": safe_tool_payload({"status": result.status, "summary": result.summary,
                                      "error_code": result.error_code, "retryable": result.retryable,
                                      "data": result.data}),
    })


def core_execute_tool(state: dict, ctx):
    plan = AgentPlan(
        id=state.get("plan_id") or "runtime-plan",
        goal=(state.get("goal") or {}).get("goal") or state.get("question") or "",
        revision=state.get("plan_revision") or 1,
        completion_criteria=state.get("completion_criteria") or [], steps=state.get("plan_steps") or [],
    )
    ready = _ready_steps(plan)
    if not ready:
        return {"_terminate": True, "final_status": "FAILED", "error_code": "AGENT_PLAN_INVALID", "error_summary": "计划没有可执行的步骤"}

    # Only independent, read-only tools are eligible for a concurrent batch.
    parallel_limit = max(1, int(ctx.settings.agent_parallel_read_limit))
    parallel_safe = all(
        (definition := ctx.tool_registry.get(step.capability).definition).risk == "READ_ONLY"
        and not definition.side_effect and not definition.requires_confirmation
        for step in ready
    )
    batch = ready[:parallel_limit] if len(ready) > 1 and parallel_safe else ready[:1]
    proposals = [ToolCallProposal(tool_name=step.capability, arguments=_arguments(step, state)) for step in batch]
    contexts = [_context(state, ctx, plan) for _step in batch]

    approval_id = state.get("pending_approval_id")
    confirmed = False
    if approval_id:
        from ..approvals import verify_approval
        try:
            verify_approval(ctx.session_factory, approval_id=approval_id, user_id=str(state.get("user_id") or ""),
                            plan_id=plan.id, tool_name=proposals[0].tool_name, arguments=proposals[0].arguments)
        except ToolError as exc:
            return {"_terminate": True, "final_status": "FAILED", "error_code": exc.code, "error_summary": exc.message}
        confirmed = True

    for step, proposal in zip(batch, proposals):
        _append_event(ctx, state["answer_id"], {
            "type": "tool.started", "call_id": proposal.call_id, "tool": proposal.tool_name,
            "step_id": step.id, "message": f"开始调用 {proposal.tool_name}",
            "input": safe_tool_payload(proposal.arguments),
        })
    if len(batch) == 1:
        results = [_execute_one(ctx, proposals[0], contexts[0], confirmed)]
    else:
        with ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix="agent-tool") as pool:
            results = list(pool.map(lambda item: _execute_one(ctx, item[0], item[1], False), zip(proposals, contexts)))

    observations = list(state.get("observations") or [])
    evidence: list[dict] = []
    degradation_flags: list[str] = []
    failed_result = None
    skill_loaded = False
    for step, proposal, (result, duration_ms) in zip(batch, proposals, results):
        _emit_completed(ctx, state["answer_id"], step, proposal, result, duration_ms)
        if result.error_code == "APPROVAL_REQUIRED":
            from ..approvals import create_approval
            approval_id = create_approval(ctx.session_factory, state=state, step_id=step.id, tool_name=proposal.tool_name,
                                          arguments=proposal.arguments,
                                          impact_summary={"tool": proposal.tool_name, "step_title": step.title,
                                                          "risk": step.risk, "summary": result.summary},
                                          ttl_minutes=ctx.settings.agent_approval_ttl_minutes)
            index = next(i for i, item in enumerate(plan.steps) if item.id == step.id)
            plan.steps[index] = step.model_copy(update={"status": "WAITING_APPROVAL"})
            return {"plan_steps": [item.model_dump(mode="json") for item in plan.steps], "active_step_id": step.id,
                    "pending_approval_id": approval_id, "suspended_reason": "等待用户确认后执行写工具",
                    "_terminate": True, "final_status": "WAITING", "observations": observations + [{
                        "step_id": step.id, "tool_name": proposal.tool_name, "status": "WAITING_APPROVAL",
                        "summary": result.summary, "error_code": result.error_code}],
                    "tool_call_count": state.get("tool_call_count", 0)}
        index = next(i for i, item in enumerate(plan.steps) if item.id == step.id)
        plan.steps[index] = step.model_copy(update={"status": "SUCCEEDED" if result.status == "SUCCEEDED" else "FAILED"})
        observations.append({"step_id": step.id, "tool_name": result.tool_name, "status": result.status,
                             "summary": result.summary, "error_code": result.error_code, "retryable": result.retryable,
                             "evidence_refs": result.evidence_refs, "data": result.data})
        try:
            from ..persistence import persist_tool_call
            persist_tool_call(ctx.session_factory, state=state | {"active_step_id": step.id}, proposal=proposal, result=result)
        except Exception:
            pass
        if result.status != "SUCCEEDED" and failed_result is None:
            failed_result = result
        data = result.data or {}
        if result.tool_name == "knowledge.search":
            evidence.extend(data.get("evidence") or [])
            degradation_flags.extend(data.get("degradation_flags") or [])
        if result.tool_name == "skill.load" and result.status == "SUCCEEDED":
            skill_loaded = True

    update = {"plan_steps": [item.model_dump(mode="json") for item in plan.steps], "active_step_id": batch[-1].id,
              "observations": observations, "tool_call_count": state.get("tool_call_count", 0) + len(batch),
              "pending_approval_id": None, "verification_result": verify_plan(plan, observations).__dict__}
    if failed_result is not None:
        update.update({"_terminate": True, "final_status": "FAILED", "error_code": failed_result.error_code or "TOOL_EXECUTION_FAILED",
                       "error_summary": failed_result.summary or "工具执行失败"})
        return update
    if evidence:
        update.update({"evidence": evidence, "degradation_flags": list(state.get("degradation_flags") or []) + degradation_flags,
                       "retrieval_queries": [state.get("normalized_question") or state.get("question") or ""]})
    if skill_loaded:
        update.update({"answer_type": "ANSWER", "final_status": "SUCCEEDED"})
    return update
