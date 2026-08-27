"""Base protocol for registered Agent tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from pydantic import BaseModel

from ..contracts.tool import ToolDefinition, ToolResultEnvelope


class ToolError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ToolContext:
    """Runtime dependencies available to tools; secrets are never model input."""

    user_id: str
    run_id: str | None = None
    plan_id: str | None = None
    session_factory: Callable | None = None
    services: dict[str, Any] = field(default_factory=dict)
    permissions: frozenset[str] = frozenset()
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentTool(Protocol):
    definition: ToolDefinition
    input_model: type[BaseModel]
    output_model: type[BaseModel]

    def execute(self, args: BaseModel, context: ToolContext) -> ToolResultEnvelope: ...
