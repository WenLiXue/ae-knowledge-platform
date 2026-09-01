"""Create and validate a bounded tool plan from the understood goal."""

from __future__ import annotations

from ..contracts.goal import GoalUnderstanding
from ..planner import PlannerLimits, plan_goal
from ..tools.base import ToolError


def core_create_plan(state: dict, ctx):
    try:
        goal = GoalUnderstanding.model_validate(state.get("goal") or {})
        permissions = {"knowledge:read", "skill:read"}
        permissions.add("mcp:read")
        if ctx.settings.agent_write_tools_enabled:
            permissions.add("task:write")
        existing_plan = None
        if state.get("plan_steps"):
            from ..contracts.plan import AgentPlan

            existing_plan = AgentPlan(
                id=state.get("plan_id") or "runtime-plan",
                goal=goal.goal,
                revision=state.get("plan_revision") or 1,
                completion_criteria=state.get("completion_criteria") or [],
                steps=state.get("plan_steps") or [],
            )
        planner_chat = None
        if ctx.settings.feature_real_qa:
            planner_chat = lambda messages, **kwargs: ctx.models.chat(
                messages,
                timeout_seconds=ctx.settings.agent_planner_timeout_seconds,
                **kwargs,
            )
        plan = plan_goal(
            goal,
            registry=ctx.tool_registry,
            permissions=frozenset(permissions),
            chat=planner_chat,
            limits=PlannerLimits(
                max_steps=ctx.settings.agent_max_plan_steps,
                max_tool_calls=ctx.settings.agent_max_tool_calls,
                max_replans=ctx.settings.agent_max_replans,
                parallel_read_limit=ctx.settings.agent_parallel_read_limit,
            ),
            observations=state.get("observations") or [],
            existing_plan=existing_plan,
        )
    except ToolError as exc:
        return {
            "_terminate": True,
            "final_status": "FAILED",
            "error_code": exc.code,
            "error_summary": exc.message,
        }
    except Exception:
        return {
            "_terminate": True,
            "final_status": "FAILED",
            "error_code": "AGENT_PLAN_INVALID",
            "error_summary": "无法生成安全的工具执行计划",
        }
    try:
        from ..persistence import persist_plan

        persist_plan(ctx.session_factory, answer_id=str(state["answer_id"]), plan=plan)
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "agent_plan_persistence_failed", extra={"answer_id": state.get("answer_id")}
        )
        return {
            "_terminate": True,
            "final_status": "FAILED",
            "error_code": "AGENT_PERSISTENCE_FAILED",
            "error_summary": "工具计划持久化失败",
        }
    return {
        "plan_id": plan.id,
        "plan_revision": plan.revision,
        "plan_steps": [step.model_dump(mode="json") for step in plan.steps],
        "completion_criteria": [item.model_dump(mode="json") for item in plan.completion_criteria],
        "active_step_id": None,
        "replan_count": state.get("replan_count", 0) + (1 if existing_plan else 0),
        "route_reason_code": "PLAN_REPLANNED" if existing_plan else "PLAN_CREATED",
    }
