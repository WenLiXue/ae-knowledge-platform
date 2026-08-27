"""Serializable plan DTOs and step lifecycle."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .goal import CompletionCriterion


class PlanStep(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=256)
    capability: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,127}$")
    depends_on: list[str] = Field(default_factory=list, max_length=12)
    input_bindings: dict[str, Any] = Field(default_factory=dict)
    expected_output: str = Field(min_length=1, max_length=500)
    verification: list[CompletionCriterion] = Field(default_factory=list, max_length=20)
    risk: Literal["READ_ONLY", "LOW_RISK_WRITE", "HIGH_RISK"] = "READ_ONLY"
    status: Literal[
        "PENDING", "READY", "WAITING_APPROVAL", "RUNNING",
        "SUCCEEDED", "FAILED", "SKIPPED",
    ] = "PENDING"


class AgentPlan(BaseModel):
    id: str
    goal: str = Field(min_length=1, max_length=2000)
    revision: int = Field(default=1, ge=1)
    status: Literal["DRAFT", "RUNNING", "WAITING", "SUCCEEDED", "PARTIAL", "FAILED", "CANCELED"] = "DRAFT"
    completion_criteria: list[CompletionCriterion] = Field(default_factory=list, max_length=50)
    steps: list[PlanStep] = Field(min_length=1, max_length=12)
