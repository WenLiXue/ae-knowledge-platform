"""General-purpose message-driven agent loop.

The model decides whether to answer or call tools. Tool execution remains
owned by the backend policy/executor; model output is never authorization.
"""

from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

from ...model_gateway.base import GatewayTool
from ..contracts.tool import ToolCallProposal
from ..contracts.plan import AgentPlan, PlanStep
from ..prompts import GENERAL_AGENT_SYSTEM_PROMPT
from ..security import permissions_for_run
from ..tools.base import ToolContext
from . import _append_event, safe_tool_payload


def _tool_context(state: dict, ctx) -> ToolContext:
    return ToolContext(
        user_id=str(state.get("user_id") or ""),
        run_id=state.get("run_id"),
        session_factory=ctx.session_factory,
        services={"retrieval_service_factory": ctx.retrieval_service_factory},
        permissions=permissions_for_run(write_tools_enabled=ctx.settings.agent_write_tools_enabled),
    )


def _answer_update(content: str, messages: list[dict], count: int) -> dict:
    text = (content or "").strip()
    return {
        "messages": messages,
        "answer_type": "ANSWER",
        "answer_summary": text,
        "answer_text": text,
        "answer_markdown": text,
        "answer_blocks": [{"block_id": "block_1", "type": "paragraph", "content": text, "citation_ids": []}] if text else [],
        "generation_completed": True,
        "final_status": "SUCCEEDED",
        "tool_call_count": count,
    }


def _approval_plan(state: dict, proposals: list[ToolCallProposal], ctx) -> tuple[AgentPlan, str]:
    plan = AgentPlan(
        id=str(uuid.uuid4()),
        goal=state.get("question") or "执行用户请求",
        steps=[
            PlanStep(
                id="call_" + re.sub(r"[^a-zA-Z0-9_-]", "", proposal.call_id)[-50:],
                title=f"调用 {proposal.tool_name}",
                capability=proposal.tool_name,
                input_bindings=proposal.arguments,
                expected_output="返回工具执行结果",
                risk=ctx.tool_registry.get(proposal.tool_name).definition.risk,
            )
            for proposal in proposals
        ],
    )
    from ..persistence import persist_plan
    persist_plan(ctx.session_factory, answer_id=str(state["answer_id"]), plan=plan)
    return plan, plan.steps[0].id


def _tool_result_message(proposal, result, limit: int) -> dict:
    return {
        "role": "tool",
        "tool_call_id": proposal.call_id,
        "content": json.dumps({"status": result.status, "summary": result.summary, "data": result.data, "error_code": result.error_code}, ensure_ascii=False, default=str)[:limit],
    }


def core_agent_loop(state: dict, ctx):
    permissions = permissions_for_run(write_tools_enabled=ctx.settings.agent_write_tools_enabled)
    definitions = ctx.tool_registry.definitions(permissions)
    tools = [GatewayTool(name=d["name"], description=d["description"], parameters=d["input_schema"]) for d in definitions]
    messages = list(state.get("messages") or [])
    if not messages or messages[-1].get("role") != "user":
        messages.append({"role": "user", "content": state.get("question") or ""})
    count = int(state.get("tool_call_count") or 0)
    max_calls = int(ctx.settings.agent_max_tool_calls)
    context = _tool_context(state, ctx)

    # Resume an approval without asking the model to repeat the tool call.
    pending = [ToolCallProposal.model_validate(item) for item in (state.get("pending_tool_calls") or [])]
    if state.get("pending_approval_id") and pending:
        from ..approvals import verify_approval
        proposal = pending[0]
        plan = AgentPlan(id=state.get("plan_id") or "", goal=state.get("question") or "执行用户请求", steps=state.get("plan_steps") or [])
        step_id = next((step.id for step in plan.steps if step.capability == proposal.tool_name), plan.steps[0].id)
        verify_approval(ctx.session_factory, approval_id=state["pending_approval_id"], user_id=str(state.get("user_id") or ""), plan_id=plan.id, tool_name=proposal.tool_name, arguments=proposal.arguments)
        result = ctx.tool_executor.execute(proposal, context, confirmed=True)
        _append_event(ctx, state["answer_id"], {"type": "tool.completed" if result.status == "SUCCEEDED" else "tool.failed", "kind": "tool", "call_id": proposal.call_id, "tool": proposal.tool_name, "message": result.summary, "status": result.status, "output": safe_tool_payload({"status": result.status, "summary": result.summary, "data": result.data})})
        messages.append(_tool_result_message(proposal, result, ctx.settings.agent_tool_result_max_bytes))
        pending = pending[1:]
        if pending:
            next_plan = plan.model_copy(update={"steps": [step.model_copy(update={"status": "PENDING"}) if step.capability == pending[0].tool_name else step for step in plan.steps]})
            from ..approvals import create_approval
            next_step = next(step for step in next_plan.steps if step.capability == pending[0].tool_name)
            approval_id = create_approval(ctx.session_factory, state={**state, "plan_id": next_plan.id, "plan_steps": [item.model_dump(mode="json") for item in next_plan.steps]}, step_id=next_step.id, tool_name=pending[0].tool_name, arguments=pending[0].arguments, impact_summary={"tool": pending[0].tool_name, "risk": next_step.risk, "summary": "模型请求执行写操作"}, ttl_minutes=ctx.settings.agent_approval_ttl_minutes)
            return {"_terminate": True, "final_status": "WAITING", "pending_approval_id": approval_id, "pending_tool_calls": [item.model_dump(mode="json") for item in pending], "plan_id": next_plan.id, "plan_steps": [item.model_dump(mode="json") for item in next_plan.steps], "active_step_id": next_step.id, "suspended_reason": "等待用户确认后执行写工具", "messages": messages, "tool_call_count": count + 1}
        count += 1
        state = {**state, "pending_approval_id": None, "pending_tool_calls": [], "messages": messages, "tool_call_count": count}

    for _turn in range(max(1, int(ctx.settings.agent_max_steps))):
        if count >= max_calls:
            return {"_terminate": True, "final_status": "FAILED", "error_code": "AGENT_TOOL_LIMIT", "error_summary": "工具调用超过安全上限", "messages": messages}
        response = ctx.models.chat_with_tools(
            [{"role": "system", "content": GENERAL_AGENT_SYSTEM_PROMPT}, *messages],
            tools=tools,
            max_tokens=4096,
        )
        assistant = {"role": "assistant", "content": response.content or ""}
        if response.tool_calls:
            assistant["tool_calls"] = [
                {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)}}
                for call in response.tool_calls
            ]
        messages.append(assistant)
        if not response.tool_calls:
            return _answer_update(response.content, messages, count)

        proposals = [ToolCallProposal(call_id=call.id, tool_name=call.name, arguments=call.arguments) for call in response.tool_calls]
        for proposal in proposals:
            _append_event(ctx, state["answer_id"], {"type": "tool.started", "kind": "tool", "call_id": proposal.call_id, "tool": proposal.tool_name, "message": f"开始调用 {proposal.tool_name}", "input": safe_tool_payload(proposal.arguments)})

        approval_proposals = [proposal for proposal in proposals if (ctx.tool_registry.get(proposal.tool_name).definition.requires_confirmation or ctx.tool_registry.get(proposal.tool_name).definition.side_effect)]
        if approval_proposals:
            plan, step_id = _approval_plan(state, proposals, ctx)
            from ..approvals import create_approval
            approval_id = create_approval(ctx.session_factory, state={**state, "plan_id": plan.id}, step_id=step_id, tool_name=approval_proposals[0].tool_name, arguments=approval_proposals[0].arguments, impact_summary={"tool": approval_proposals[0].tool_name, "risk": plan.steps[0].risk, "summary": "模型请求执行写操作"}, ttl_minutes=ctx.settings.agent_approval_ttl_minutes)
            return {"_terminate": True, "final_status": "WAITING", "pending_approval_id": approval_id, "pending_tool_calls": [item.model_dump(mode="json") for item in proposals], "plan_id": plan.id, "plan_steps": [item.model_dump(mode="json") for item in plan.steps], "active_step_id": step_id, "suspended_reason": "等待用户确认后执行写工具", "messages": messages, "tool_call_count": count}

        def execute(proposal):
            return proposal, ctx.tool_executor.execute(proposal, context, confirmed=False)

        if len(proposals) > 1 and all(
            (definition := ctx.tool_registry.get(proposal.tool_name).definition).risk == "READ_ONLY"
            and not definition.side_effect and not definition.requires_confirmation
            for proposal in proposals
        ):
            with ThreadPoolExecutor(max_workers=len(proposals), thread_name_prefix="agent-tool") as pool:
                results = list(pool.map(execute, proposals))
        else:
            results = [execute(proposal) for proposal in proposals]

        for proposal, result in results:
            count += 1
            _append_event(ctx, state["answer_id"], {"type": "tool.completed" if result.status == "SUCCEEDED" else "tool.failed", "kind": "tool", "call_id": proposal.call_id, "tool": proposal.tool_name, "message": result.summary, "status": result.status, "output": safe_tool_payload({"status": result.status, "summary": result.summary, "error_code": result.error_code, "data": result.data})})
            messages.append(_tool_result_message(proposal, result, ctx.settings.agent_tool_result_max_bytes))

    return {"_terminate": True, "final_status": "FAILED", "error_code": "AGENT_STEP_LIMIT_EXCEEDED", "error_summary": "Agent 执行超过安全步数上限", "messages": messages, "tool_call_count": count}
