"""Compatibility aggregator for Agent capability administration routes."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import get_current_admin
from ..db.models.capability import AgentMcpServer, AgentSkill, AgentToolConfig
from ..db.models.user import User
from ..db.session import get_db
from .admin import mcp_api, skills_api, tools_api
from .capability.serializers import mcp_dict, skill_dict, tool_dict
from .tools.bootstrap import build_default_tool_registry

router = APIRouter(prefix="/api/v1/admin/agent", tags=["admin-agent-capabilities"])
router.include_router(tools_api.router)
router.include_router(skills_api.router)
router.include_router(mcp_api.router)


@router.get("/capabilities")
def list_capabilities(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    # Keep the admin catalog complete even after introducing a new code-owned
    # tool.  The database stores only enablement; definitions remain owned by
    # the runtime registry.
    configured = {row.name: row for row in db.execute(select(AgentToolConfig)).scalars()}
    changed = False
    for definition in build_default_tool_registry().definitions():
        if definition["name"] in configured:
            continue
        row = AgentToolConfig(
            name=definition["name"], version=definition["version"],
            description=definition["description"], enabled=False, source="BUILTIN",
        )
        db.add(row)
        configured[row.name] = row
        changed = True
    if changed:
        db.commit()
    tools = list(db.execute(select(AgentToolConfig).order_by(AgentToolConfig.name)).scalars())
    skills = list(db.execute(select(AgentSkill).order_by(AgentSkill.name)).scalars())
    mcp_servers = list(db.execute(select(AgentMcpServer).order_by(AgentMcpServer.name)).scalars())
    return {"data": {"tools": [tool_dict(row) for row in tools],
                      "skills": [skill_dict(row) for row in skills],
                      "mcp_servers": [mcp_dict(row) for row in mcp_servers]}}
