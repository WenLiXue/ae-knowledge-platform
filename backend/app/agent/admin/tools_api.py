"""Tool enablement administration routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...auth.deps import get_current_admin
from ...db.models.capability import AgentToolConfig
from ...db.models.user import User
from ...db.session import get_db
from ..capability.serializers import tool_dict
from ..tools.bootstrap import build_default_tool_registry
from .schemas import EnabledPatch

router = APIRouter(tags=["admin-agent-capabilities"])


@router.patch("/tools/{tool_name}")
def set_tool_enabled(tool_name: str, data: EnabledPatch, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    row = db.get(AgentToolConfig, tool_name)
    if row is None:
        definition = next((item for item in build_default_tool_registry().definitions() if item["name"] == tool_name), None)
        if definition is None:
            raise HTTPException(status_code=404, detail={"code": "TOOL_NOT_FOUND", "message": "工具不存在"})
        row = AgentToolConfig(
            name=tool_name, version=definition["version"],
            description=definition["description"], enabled=False, source="BUILTIN",
        )
        db.add(row)
    row.enabled = data.enabled
    db.commit()
    return {"data": tool_dict(row)}
