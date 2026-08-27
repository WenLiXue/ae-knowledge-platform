"""Execute one ready tool step through the registry and policy boundary."""

from __future__ import annotations

from ..contracts.plan import AgentPlan
from ..contracts.tool import ToolCallProposal
from ..verifier import verify_plan
from ..tools.base import ToolContext, ToolError


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
    permissions = {"knowledge:read", "skill:read"}
    if ctx.settings.agent_write_tools_enabled:
        permissions.add("task:write")
    tool_context = ToolContext(
        user_id=str(state.get("user_id") or ""),
        run_id=state.get("run_id"),
        plan_id=plan.id,
        session_factory=ctx.session_factory,
        services={"retrieval_service_factory": ctx.retrieval_service_factory},
        # Knowledge access is the same read permission used by the existing
        # authenticated retrieval path. Admin/action permissions are not granted.
        permissions=frozenset(permissions),
    )
    approval_id = state.get("pending_approval_id")
    confirmed = False
    if approval_id:
        from ..approvals import verify_approval

        try:
            verify_approval(
                ctx.session_factory,
                approval_id=approval_id,
                user_id=str(state.get("user_id") or ""),
                plan_id=plan.id,
                tool_name=proposal.tool_name,
                arguments=proposal.arguments,
            )
        except ToolError as exc:
            return {
                "_terminate": True,
                "final_status": "FAILED",
                "error_code": exc.code,
                "error_summary": exc.message,
            }
        confirmed = True
    result = ctx.tool_executor.execute(proposal, tool_context, confirmed=confirmed)
    index = next(i for i, item in enumerate(plan.steps) if item.id == step.id)
    if result.error_code == "APPROVAL_REQUIRED":
        from ..approvals import create_approval

        approval_id = create_approval(
            ctx.session_factory,
            state=state,
            step_id=step.id,
            tool_name=proposal.tool_name,
            arguments=proposal.arguments,
            impact_summary={
                "tool": proposal.tool_name,
                "step_title": step.title,
                "risk": step.risk,
                "summary": result.summary,
            },
            ttl_minutes=ctx.settings.agent_approval_ttl_minutes,
        )
        plan.steps[index] = step.model_copy(update={"status": "WAITING_APPROVAL"})
        return {
            "plan_steps": [item.model_dump(mode="json") for item in plan.steps],
            "active_step_id": step.id,
            "pending_approval_id": approval_id,
            "suspended_reason": "等待用户确认后执行写工具",
            "_terminate": True,
            "final_status": "WAITING",
            "observations": list(state.get("observations") or []) + [{
                "step_id": step.id,
                "tool_name": proposal.tool_name,
                "status": "WAITING_APPROVAL",
                "summary": result.summary,
                "error_code": result.error_code,
            }],
            "tool_call_count": state.get("tool_call_count", 0),
        }
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
    try:
        from ..persistence import persist_tool_call

        persist_tool_call(ctx.session_factory, state=state | {"active_step_id": step.id}, proposal=proposal, result=result)
    except Exception:
        # Execution result remains authoritative for this run; metadata write
        # failure is observable but must not turn a successful read into a fake
        # business failure.
        pass
    update = {
        "plan_steps": [item.model_dump(mode="json") for item in plan.steps],
        "active_step_id": step.id,
        "observations": observations,
        "tool_call_count": state.get("tool_call_count", 0) + 1,
        "pending_approval_id": None,
        "verification_result": verify_plan(plan, observations).__dict__,
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
    elif result.tool_name == "skill.load":
        update["answer_type"] = "ANSWER"
        update["final_status"] = "SUCCEEDED"
    return update
