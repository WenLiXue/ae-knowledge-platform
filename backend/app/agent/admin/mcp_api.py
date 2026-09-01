"""MCP server administration and discovery routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...auth.deps import get_current_admin
from ...db.models.capability import AgentMcpServer
from ...db.models.user import User
from ...db.session import get_db
from ..capability.serializers import mcp_dict
from ..mcp_client import McpDiscoveryError, discover
from .schemas import EnabledPatch, McpCreate

router = APIRouter(tags=["admin-agent-capabilities"])


@router.post("/mcp-servers", status_code=201)
def create_mcp_server(data: McpCreate, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    if db.execute(select(AgentMcpServer).where(AgentMcpServer.name == data.name)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail={"code": "MCP_SERVER_EXISTS", "message": "MCP Server 名称已存在"})
    row = AgentMcpServer(name=data.name, endpoint=str(data.endpoint), description=data.description, transport=data.transport, auth_type=data.auth_type, enabled=data.enabled, status="NOT_TESTED", created_by=admin.id)
    db.add(row); db.commit(); db.refresh(row)
    return {"data": mcp_dict(row)}


@router.patch("/mcp-servers/{server_id}")
def set_mcp_enabled(server_id: uuid.UUID, data: EnabledPatch, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    row = db.get(AgentMcpServer, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "MCP_SERVER_NOT_FOUND", "message": "MCP Server 不存在"})
    row.enabled = data.enabled; row.status = "ENABLED" if data.enabled else "DISABLED"
    db.commit()
    return {"data": mcp_dict(row)}


@router.post("/mcp-servers/{server_id}/discover")
def discover_mcp_tools(server_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    row = db.get(AgentMcpServer, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "MCP_SERVER_NOT_FOUND", "message": "MCP Server 不存在"})
    try:
        row.discovered_tools = discover(row.endpoint)
    except McpDiscoveryError as exc:
        row.status = "ERROR"; row.last_error = str(exc)[:512]; db.commit()
        raise HTTPException(status_code=502, detail={"code": "MCP_DISCOVERY_FAILED", "message": "MCP 工具发现失败"}) from exc
    row.status = "READY"; row.last_error = None; db.commit(); db.refresh(row)
    return {"data": mcp_dict(row)}
