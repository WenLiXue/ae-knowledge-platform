"""Public Agent Run event contract shared by runtime, persistence and UI."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


EventType = Literal[
    "run.started", "run.completed", "run.failed", "run.cancelled",
    "phase.started", "phase.completed",
    "step.started", "step.progress", "step.completed", "step.failed",
    "approval.required", "approval.approved", "approval.rejected",
    "generation.started", "generation.delta", "generation.completed",
    "answer.finalized",
]
EventKind = Literal["reasoning", "tool", "skill", "retrieval", "mcp", "workflow", "generation"]


class AgentEvent(BaseModel):
    """A safe, resumable event; raw prompts and unredacted tool output are excluded."""

    event_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    seq: int = Field(ge=1)
    timestamp: str
    type: EventType
    kind: EventKind
    phase: str | None = Field(default=None, max_length=64)
    step_id: str | None = Field(default=None, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1000)
    status: str | None = Field(default=None, max_length=32)
    summary: str | None = Field(default=None, max_length=2000)
    duration_ms: float | None = Field(default=None, ge=0)
    input: Any | None = None
    output: Any | None = None
