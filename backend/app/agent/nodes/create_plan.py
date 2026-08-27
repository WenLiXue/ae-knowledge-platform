"""Create and validate a bounded tool plan from the understood goal."""

from __future__ import annotations

from ..contracts.goal import GoalUnderstanding
from ..planner import PlannerLimits, plan_goal
from ..tools.base import ToolError


def core_create_plan(state: dict, ctx):
    try:
        goal = GoalUnderstanding.model_validate(state.get("goal") or {})
        permissions = {"knowledge:read", "skill:read"}
        if ctx.settings.agent_write_tools_enabled:
            permissions.add("task:write")
        plan = plan_goal(
            goal,
            registry=ctx.tool_registry,
            permissions=frozenset(permissions),
            chat=(ctx.models.chat if ctx.settings.feature_real_qa else None),
            limits=PlannerLimits(
                max_steps=ctx.settings.agent_max_plan_steps,
                max_tool_calls=ctx.settings.agent_max_tool_calls,
                max_replans=ctx.settings.agent_max_replans,
                parallel_read_limit=ctx.settings.agent_parallel_read_limit,
            ),
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
        "route_reason_code": "PLAN_CREATED",
    }
