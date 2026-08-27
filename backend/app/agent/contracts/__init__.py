"""Stable contracts shared by the tool registry, planner and executor."""

from .goal import CompletionCriterion, Constraint, EntityRef, GoalUnderstanding
from .plan import AgentPlan, PlanStep
from .tool import (
    ToolCallProposal,
    ToolDefinition,
    ToolResultEnvelope,
    ToolStatus,
)

__all__ = [
    "CompletionCriterion",
    "Constraint",
    "EntityRef",
    "GoalUnderstanding",
    "AgentPlan",
    "PlanStep",
    "ToolCallProposal",
    "ToolDefinition",
    "ToolResultEnvelope",
    "ToolStatus",
]
