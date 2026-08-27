"""Small, deterministic tool-agent execution engine.

LangGraph can host this engine later; keeping execution semantics here makes
the tool boundary independently testable and avoids hard-coding RAG branches
into the graph.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .contracts.goal import GoalUnderstanding
from .contracts.plan import AgentPlan
from .contracts.tool import ToolCallProposal
from .planner import PlannerLimits, plan_goal
from .tools.base import ToolContext
from .tools.executor import ToolExecutor
from .tools.registry import ToolRegistry
from .verifier import Verification, verify_plan


class ToolAgentEngine:
    def __init__(
        self,
        registry: ToolRegistry,
        executor: ToolExecutor | None = None,
        *,
        limits: PlannerLimits | None = None,
    ) -> None:
        self.registry = registry
        self.executor = executor or ToolExecutor(registry)
        self.limits = limits or PlannerLimits()

    def run(
        self,
        goal: GoalUnderstanding,
        context: ToolContext,
        *,
        plan: AgentPlan | None = None,
        planner_chat=None,
    ) -> tuple[AgentPlan, list[dict], Verification]:
        permissions = context.permissions
        plan = plan or plan_goal(
            goal,
            registry=self.registry,
            permissions=permissions,
            chat=planner_chat,
            limits=self.limits,
        )
        observations: list[dict] = []
        calls = 0
        while calls < self.limits.max_tool_calls:
            ready = [step_id for step_id in self._ready(plan) if self._step(plan, step_id).status != "WAITING_APPROVAL"]
            if not ready:
                break
            step_id = ready[0]
            step = self._step(plan, step_id)
            arguments = self._bind(step.input_bindings, goal, observations)
            proposal = ToolCallProposal(tool_name=step.capability, arguments=arguments)
            step_index = next(i for i, item in enumerate(plan.steps) if item.id == step_id)
            plan.steps[step_index] = step.model_copy(update={"status": "RUNNING"})
            result = self.executor.execute(proposal, context)
            calls += 1
            observations.append({
                "step_id": step_id,
                "tool_name": result.tool_name,
                "status": result.status,
                "retryable": result.retryable,
                "error_code": result.error_code,
                "summary": result.summary,
                "evidence_refs": result.evidence_refs,
                "data": result.data,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            new_status = "SUCCEEDED" if result.status == "SUCCEEDED" else "FAILED"
            plan.steps[step_index] = step.model_copy(update={"status": new_status})
            if new_status == "FAILED" and not result.retryable:
                break
        verification = verify_plan(plan, observations)
        if verification.complete:
            plan.status = "SUCCEEDED"
        elif verification.needs_replan:
            plan.status = "PARTIAL"
        else:
            plan.status = "FAILED" if any(s.status == "FAILED" for s in plan.steps) else "PARTIAL"
        return plan, observations, verification

    @staticmethod
    def _step(plan: AgentPlan, step_id: str):
        return next(step for step in plan.steps if step.id == step_id)

    @staticmethod
    def _ready(plan: AgentPlan) -> list[str]:
        done = {step.id for step in plan.steps if step.status == "SUCCEEDED"}
        return [
            step.id for step in plan.steps
            if step.status in ("PENDING", "READY") and set(step.depends_on).issubset(done)
        ]

    @staticmethod
    def _bind(bindings: dict, goal: GoalUnderstanding, observations: list[dict]) -> dict:
        """Resolve only explicit, non-executable bindings from a plan."""
        bound: dict = {}
        for key, value in bindings.items():
            if isinstance(value, str) and value == "$goal":
                bound[key] = goal.goal
            elif isinstance(value, str) and value.startswith("$observation."):
                field = value.split(".", 1)[1]
                bound[key] = observations[-1].get(field) if observations else None
            else:
                bound[key] = value
        return bound
