"""Goal and task contracts.

These DTOs deliberately describe the user's goal and completion conditions,
not hidden model reasoning. They are safe to persist in checkpoints.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EntityRef(BaseModel):
    entity_type: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=256)
    source: Literal["USER", "CONTEXT", "TOOL"] = "USER"


class Constraint(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    value: str | int | float | bool | list[str] | dict = Field(max_length=4096)
    source: Literal["USER", "SYSTEM", "TOOL"] = "USER"


class CompletionCriterion(BaseModel):
    type: Literal[
        "EVIDENCE_BOUND",
        "SET_COVERAGE",
        "REQUIRED_FIELDS",
        "OUTPUT_SHAPE",
        "ACTION_CONFIRMED",
        "ACTION_VERIFIED",
    ]
    required: bool = True
    params: dict = Field(default_factory=dict)


class GoalUnderstanding(BaseModel):
    intent: Literal[
        "CHAT",
        "EXPLAIN",
        "KNOWLEDGE_QUERY",
        "ANALYZE",
        "TASK",
        "ACTION",
        "CLARIFY",
    ]
    operation: str | None = None
    goal: str = Field(min_length=1, max_length=2000)
    entities: list[EntityRef] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    completion_criteria: list[CompletionCriterion] = Field(default_factory=list)
    requires_enterprise_evidence: bool = False
    candidate_capabilities: list[str] = Field(default_factory=list)
    ambiguity: list[str] = Field(default_factory=list)
    risk_hint: Literal["NONE", "READ_ONLY", "WRITE", "HIGH_RISK"] = "NONE"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
