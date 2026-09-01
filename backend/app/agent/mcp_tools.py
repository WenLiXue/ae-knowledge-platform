"""Adapter exposing a discovered MCP tool through the normal tool runtime."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from .contracts.tool import ToolDefinition, ToolResultEnvelope
from .tools.base import ToolContext, ToolError
from .mcp_client import McpDiscoveryError, rpc


class McpArguments(BaseModel):
    model_config = ConfigDict(extra="allow")


class McpRemoteTool:
    input_model = McpArguments
    output_model = McpArguments

    def __init__(self, endpoint: str, server_name: str, item: dict[str, Any]):
        self.endpoint = endpoint
        self.remote_name = item["name"]
        self.definition = ToolDefinition(
            name=f"mcp.{server_name}.{item['name']}", version="1.0",
            description=item.get("description") or f"MCP 工具 {item['name']}",
            input_schema=item.get("input_schema") or {"type": "object"},
            output_schema={"type": "object"}, layer="RESOURCE", owner=f"mcp:{server_name}",
            risk="HIGH_RISK", side_effect=True, requires_confirmation=True,
            idempotency="NOT_APPLICABLE", required_permissions=["mcp:read"],
            timeout_seconds=30, max_retries=0, sensitivity="INTERNAL",
        )

    def execute(self, args: McpArguments, context: ToolContext) -> ToolResultEnvelope:
        try:
            headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
            with httpx.Client(timeout=self.definition.timeout_seconds) as client:
                result = rpc(client, self.endpoint, "tools/call", {
                    "name": self.remote_name, "arguments": args.model_dump(exclude_unset=True),
                }, headers)
        except (McpDiscoveryError, httpx.HTTPError) as exc:
            raise ToolError("MCP_TOOL_FAILED", "MCP 工具调用失败", retryable=True) from exc
        now = datetime.now(timezone.utc)
        return ToolResultEnvelope(
            call_id=str(context.metadata.get("call_id") or uuid.uuid4()),
            tool_name=self.definition.name, tool_version=self.definition.version,
            status="SUCCEEDED", data=result if isinstance(result, dict) else {"result": result},
            summary="MCP 工具执行完成", started_at=now, completed_at=datetime.now(timezone.utc),
        )
