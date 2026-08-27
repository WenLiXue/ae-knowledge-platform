"""Execute one ready tool step through the registry and policy boundary."""

from __future__ import annotations

from ..contracts.plan import AgentPlan
from ..contracts.tool import ToolCallProposal
from ..tools.base import ToolContext


def core_execute_tool(state: dict, ctx):
    plan = AgentPlan(
        id=state.get("plan_id") or "runtime-plan",
        goal=(state.get("goal") or {}).get("goal") or state.get("question") or "",
        revision=state.get("plan_revision") or 1,
        completion_criteria=state.get("completion_criteria") or [],
        steps=state.get("plan_steps") or [],
    )
    ready = [step for step in plan.steps if step.status in ("PENDING", "READY") and all(
        next((dep for dep in plan.steps if dep.id == dependency), None) is not None
        and next(dep for dep in plan.steps if dep.id == dependency).status == "SUCCEEDED"
        for dependency in step.depends_on
    )]
    if not ready:
        return {
            "_terminate": True,
            "final_status": "FAILED",
            "error_code": "AGENT_PLAN_INVALID",
            "error_summary": "计划没有可执行的步骤",
        }
    step = ready[0]
    arguments = dict(step.input_bindings)
    for key, value in list(arguments.items()):
        if value == "$goal":
            arguments[key] = state.get("normalized_question") or state.get("question") or ""
    proposal = ToolCallProposal(tool_name=step.capability, arguments=arguments)
    tool_context = ToolContext(
        user_id=str(state.get("user_id") or ""),
        run_id=state.get("run_id"),
        plan_id=plan.id,
        session_factory=ctx.session_factory,
        services={"retrieval_service_factory": ctx.retrieval_service_factory},
        # Knowledge access is the same read permission used by the existing
        # authenticated retrieval path. Admin/action permissions are not granted.
        permissions=frozenset({"knowledge:read"}),
    )
    result = ctx.tool_executor.execute(proposal, tool_context)
    index = next(i for i, item in enumerate(plan.steps) if item.id == step.id)
    plan.steps[index] = step.model_copy(update={"status": "SUCCEEDED" if result.status == "SUCCEEDED" else "FAILED"})
    observations = list(state.get("observations") or [])
    observations.append({
        "step_id": step.id,
        "tool_name": result.tool_name,
        "status": result.status,
        "summary": result.summary,
        "error_code": result.error_code,
        "retryable": result.retryable,
        "evidence_refs": result.evidence_refs,
        "data": result.data,
    })
    update = {
        "plan_steps": [item.model_dump(mode="json") for item in plan.steps],
        "active_step_id": step.id,
        "observations": observations,
        "tool_call_count": state.get("tool_call_count", 0) + 1,
    }
    if result.status != "SUCCEEDED":
        update.update({
            "_terminate": True,
            "final_status": "FAILED",
            "error_code": result.error_code or "TOOL_EXECUTION_FAILED",
            "error_summary": result.summary or "工具执行失败",
        })
        return update
    data = result.data or {}
    if result.tool_name == "knowledge.search":
        update["evidence"] = data.get("evidence") or []
        update["evidence_status_raw"] = data.get("evidence_status")
        update["retrieval_run_id"] = data.get("retrieval_run_id")
        update["retrieval_queries"] = [state.get("normalized_question") or state.get("question") or ""]
        update["degradation_flags"] = list(state.get("degradation_flags") or []) + list(data.get("degradation_flags") or [])
    return update
