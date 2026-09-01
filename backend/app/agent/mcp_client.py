"""Small bounded MCP JSON-RPC client used for discovery and calls."""

from __future__ import annotations

import uuid
from typing import Any

import httpx


class McpDiscoveryError(Exception):
    pass


def rpc(client: httpx.Client, endpoint: str, method: str, params: dict, headers: dict) -> Any:
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


def discover(endpoint: str, *, timeout_seconds: float = 10.0) -> list[dict[str, Any]]:
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
        session = rpc(client, endpoint, "initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "ae-knowledge-platform", "version": "1.0"},
        }, headers)
        if isinstance(session, dict):
            headers["Mcp-Session-Id"] = str(session.get("sessionId", ""))
        result = rpc(client, endpoint, "tools/list", {}, headers)
    raw_tools = result.get("tools", []) if isinstance(result, dict) else []
    return [{
        "name": str(item["name"]),
        "description": str(item.get("description") or ""),
        "input_schema": item.get("inputSchema") or {"type": "object"},
        "source": "MCP",
    } for item in raw_tools if isinstance(item, dict) and item.get("name")]
