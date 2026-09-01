"""Small, bounded MCP tool discovery client.

Discovery is deliberately separated from execution: discovered definitions are
metadata only and are never executable until an MCP runtime is configured.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict
from ..contracts.tool import ToolDefinition, ToolResultEnvelope
from .base import ToolContext, ToolError


class McpDiscoveryError(Exception):
    pass


class McpArguments(BaseModel):
    model_config = ConfigDict(extra="allow")


class McpRemoteTool:
    """A discovered MCP tool exposed through the normal ToolExecutor policy."""
    input_model = McpArguments
    output_model = McpArguments

    def __init__(self, endpoint: str, server_name: str, item: dict[str, Any]):
        self.endpoint = endpoint
        self.definition = ToolDefinition(
            name=f"mcp.{server_name}.{item['name']}", version="1.0",
            description=item.get("description") or f"MCP 工具 {item['name']}",
            input_schema=item.get("input_schema") or {"type": "object"},
            output_schema={"type": "object"}, layer="RESOURCE", owner=f"mcp:{server_name}",
            # MCP discovery cannot reliably prove a remote tool's side effects.
            # Treat unknown tools as high-risk until an explicit allowlist and
            # confirmation policy exists.
            risk="HIGH_RISK", side_effect=True, requires_confirmation=True,
            idempotency="NOT_APPLICABLE", required_permissions=["mcp:read"],
            timeout_seconds=30, max_retries=0, sensitivity="INTERNAL",
        )
        self.remote_name = item["name"]

    def execute(self, args: McpArguments, context: ToolContext) -> ToolResultEnvelope:
        try:
            with httpx.Client(timeout=self.definition.timeout_seconds) as client:
                result = _rpc(client, self.endpoint, "tools/call", {
                    "name": self.remote_name, "arguments": args.model_dump(exclude_unset=True),
                }, {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"})
        except (McpDiscoveryError, httpx.HTTPError) as exc:
            raise ToolError("MCP_TOOL_FAILED", "MCP 工具调用失败", retryable=True) from exc
        now = datetime.now(timezone.utc)
        return ToolResultEnvelope(call_id=str(context.metadata.get("call_id") or uuid.uuid4()),
            tool_name=self.definition.name, tool_version=self.definition.version, status="SUCCEEDED",
            data=result if isinstance(result, dict) else {"result": result}, summary="MCP 工具执行完成",
            started_at=now, completed_at=datetime.now(timezone.utc))


def register_discovered_tools(registry, db) -> None:
    """Load enabled, previously discovered MCP definitions into the registry."""
    from ..db.models.capability import AgentMcpServer
    for server in db.query(AgentMcpServer).filter(AgentMcpServer.enabled.is_(True)).all():
        for item in server.discovered_tools or []:
            try:
                registry.register(McpRemoteTool(server.endpoint, server.name, item))
            except (KeyError, ValueError):
                continue


def discover_tools(endpoint: str, *, timeout_seconds: float = 10.0) -> list[dict[str, Any]]:
    """Run MCP initialize + tools/list and return normalized lightweight tools."""
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
        session_id = _rpc(client, endpoint, "initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "ae-knowledge-platform", "version": "1.0"},
        }, headers)
        if isinstance(session_id, dict):
            headers["Mcp-Session-Id"] = str(session_id.get("sessionId", ""))
        result = _rpc(client, endpoint, "tools/list", {}, headers)
    raw_tools = result.get("tools", []) if isinstance(result, dict) else []
    normalized: list[dict[str, Any]] = []
    for item in raw_tools:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        normalized.append({
            "name": str(item["name"]),
            "description": str(item.get("description") or ""),
            "input_schema": item.get("inputSchema") or {"type": "object"},
            "source": "MCP",
        })
    return normalized


def _rpc(client: httpx.Client, endpoint: str, method: str, params: dict, headers: dict) -> Any:
    payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}
    try:
        response = client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise McpDiscoveryError("MCP 服务连接失败") from exc
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        data = next((line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")), "")
        body = httpx.Response(200, text=data).json() if data else {}
    else:
        body = response.json()
    if body.get("error"):
        raise McpDiscoveryError(str(body["error"].get("message") or "MCP 请求失败"))
    return body.get("result", {})
