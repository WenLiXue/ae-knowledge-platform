"""Tool-facing contracts. Model output is only a proposal; it is never execution authority."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ToolStatus = Literal["SUCCEEDED", "FAILED", "UNKNOWN", "CANCELED"]


class ToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,127}$")
    version: str = Field(pattern=r"^\d+\.\d+$")
    description: str = Field(min_length=1, max_length=1000)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    # Tool taxonomy is metadata for routing/observability; execution remains
    # protected by the same runtime policy regardless of layer.
    layer: Literal["PRIMITIVE", "RESOURCE", "DOMAIN", "WORKFLOW"] = "DOMAIN"
    owner: str = Field(default="platform", min_length=1, max_length=128)
    risk: Literal["READ_ONLY", "LOW_RISK_WRITE", "HIGH_RISK"]
    side_effect: bool
    requires_confirmation: bool
    idempotency: Literal["REQUIRED", "OPTIONAL", "NOT_APPLICABLE"]
    required_permissions: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    max_retries: int = Field(default=0, ge=0, le=3)
    max_result_bytes: int = Field(default=65536, ge=1024, le=10_000_000)
    sensitivity: Literal["PUBLIC", "INTERNAL", "RESTRICTED"] = "INTERNAL"


class ToolCallProposal(BaseModel):
    call_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultEnvelope(BaseModel):
    call_id: str
    tool_name: str
    tool_version: str
    status: ToolStatus
    data: dict[str, Any] | None = None
    summary: str = Field(default="", max_length=2000)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None
    retryable: bool = False
    truncated: bool = False
    sensitivity: Literal["PUBLIC", "INTERNAL", "RESTRICTED"] = "INTERNAL"
    started_at: datetime
    completed_at: datetime
