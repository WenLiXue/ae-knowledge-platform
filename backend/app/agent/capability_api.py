"""Administrator-only Agent capability management API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import get_current_admin
from ..db.models.capability import AgentMcpServer, AgentSkill, AgentToolConfig
from ..db.models.user import User
from ..db.session import get_db
from .capabilities import parse_skill_document
from .mcp import McpDiscoveryError, discover_tools

router = APIRouter(prefix="/api/v1/admin/agent", tags=["admin-agent-capabilities"])


class EnabledPatch(BaseModel):
    enabled: bool


class SkillCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str = Field(min_length=1, max_length=1024)
    content: str = Field(min_length=1)
    version: str = Field(default="1.0.0", max_length=32)
    enabled: bool = True


class McpCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]{1,63}$")
    endpoint: HttpUrl
    description: str = Field(default="", max_length=1024)
    transport: str = Field(default="STREAMABLE_HTTP", pattern=r"^(STREAMABLE_HTTP|SSE)$")
    auth_type: str = Field(default="NONE", pattern=r"^(NONE|OAUTH2|BEARER)$")
    enabled: bool = False


def _tool_dict(row: AgentToolConfig) -> dict:
    return {"name": row.name, "version": row.version, "description": row.description,
            "enabled": row.enabled, "source": row.source}


def _skill_dict(row: AgentSkill, *, include_content: bool = False) -> dict:
    result = {"id": str(row.id), "name": row.name, "description": row.description,
              "version": row.version, "enabled": row.enabled, "source": row.source,
              "created_at": row.created_at.isoformat() if row.created_at else None,
              "updated_at": row.updated_at.isoformat() if row.updated_at else None}
    if include_content:
        result["content"] = row.content
    return result


def _mcp_dict(row: AgentMcpServer) -> dict:
    return {"id": str(row.id), "name": row.name, "endpoint": row.endpoint,
            "description": row.description, "transport": row.transport,
            "auth_type": row.auth_type, "enabled": row.enabled,
            "status": row.status, "last_error": row.last_error,
            "discovered_tools": row.discovered_tools or [],
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


@router.get("/capabilities")
def list_capabilities(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    tools = list(db.execute(select(AgentToolConfig).order_by(AgentToolConfig.name)).scalars())
    skills = list(db.execute(select(AgentSkill).order_by(AgentSkill.name)).scalars())
    mcp_servers = list(db.execute(select(AgentMcpServer).order_by(AgentMcpServer.name)).scalars())
    return {"data": {"tools": [_tool_dict(row) for row in tools],
                      "skills": [_skill_dict(row) for row in skills],
                      "mcp_servers": [_mcp_dict(row) for row in mcp_servers]}}


@router.patch("/tools/{tool_name}")
def set_tool_enabled(tool_name: str, data: EnabledPatch, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    row = db.get(AgentToolConfig, tool_name)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "TOOL_NOT_FOUND", "message": "工具不存在"})
    row.enabled = data.enabled
    db.commit()
    return {"data": _tool_dict(row)}


@router.post("/skills", status_code=201)
def create_skill(data: SkillCreate, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    try:
        front_name, front_description = parse_skill_document(data.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "SKILL_INVALID", "message": str(exc)}) from exc
    if front_name != data.name or front_description != data.description:
        raise HTTPException(status_code=422, detail={"code": "SKILL_METADATA_MISMATCH", "message": "请求字段必须与 SKILL.md frontmatter 一致"})
    if db.execute(select(AgentSkill).where(AgentSkill.name == data.name)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail={"code": "SKILL_EXISTS", "message": "技能名称已存在"})
    row = AgentSkill(name=data.name, description=data.description, content=data.content,
                     version=data.version, enabled=data.enabled, created_by=admin.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"data": _skill_dict(row)}


@router.post("/skills/import", status_code=201)
async def import_skill(file: UploadFile = File(...), db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    if not file.filename or not file.filename.lower().endswith(".md"):
        raise HTTPException(status_code=422, detail={"code": "SKILL_FILE_INVALID", "message": "只能导入 .md 技能文件"})
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
        name, description = parse_skill_document(content)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "SKILL_INVALID", "message": str(exc)}) from exc
    if db.execute(select(AgentSkill).where(AgentSkill.name == name)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail={"code": "SKILL_EXISTS", "message": "技能名称已存在"})
    row = AgentSkill(name=name, description=description, content=content, created_by=admin.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"data": _skill_dict(row)}


@router.patch("/skills/{skill_id}")
def set_skill_enabled(skill_id: uuid.UUID, data: EnabledPatch, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    row = db.get(AgentSkill, skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "SKILL_NOT_FOUND", "message": "技能不存在"})
    row.enabled = data.enabled
    db.commit()
    return {"data": _skill_dict(row)}


@router.post("/mcp-servers", status_code=201)
def create_mcp_server(data: McpCreate, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    if db.execute(select(AgentMcpServer).where(AgentMcpServer.name == data.name)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail={"code": "MCP_SERVER_EXISTS", "message": "MCP Server 名称已存在"})
    row = AgentMcpServer(name=data.name, endpoint=str(data.endpoint), description=data.description,
                         transport=data.transport, auth_type=data.auth_type, enabled=data.enabled,
                         status="NOT_TESTED", created_by=admin.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"data": _mcp_dict(row)}


@router.patch("/mcp-servers/{server_id}")
def set_mcp_enabled(server_id: uuid.UUID, data: EnabledPatch, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    row = db.get(AgentMcpServer, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "MCP_SERVER_NOT_FOUND", "message": "MCP Server 不存在"})
    row.enabled = data.enabled
    row.status = "ENABLED" if data.enabled else "DISABLED"
    db.commit()
    return {"data": _mcp_dict(row)}


@router.post("/mcp-servers/{server_id}/discover")
def discover_mcp_tools(server_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    row = db.get(AgentMcpServer, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "MCP_SERVER_NOT_FOUND", "message": "MCP Server 不存在"})
    try:
        tools = discover_tools(row.endpoint)
    except McpDiscoveryError as exc:
        row.status = "ERROR"
        row.last_error = str(exc)[:512]
        db.commit()
        raise HTTPException(status_code=502, detail={"code": "MCP_DISCOVERY_FAILED", "message": "MCP 工具发现失败"}) from exc
    row.discovered_tools = tools
    row.status = "READY"
    row.last_error = None
    db.commit()
    db.refresh(row)
    return {"data": _mcp_dict(row)}
