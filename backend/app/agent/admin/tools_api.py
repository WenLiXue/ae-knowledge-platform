"""Tool enablement administration routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...auth.deps import get_current_admin
from ...db.models.capability import AgentToolConfig
from ...db.models.user import User
from ...db.session import get_db
from ..capability.serializers import tool_dict
from .schemas import EnabledPatch

router = APIRouter(tags=["admin-agent-capabilities"])


@router.patch("/tools/{tool_name}")
def set_tool_enabled(tool_name: str, data: EnabledPatch, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    row = db.get(AgentToolConfig, tool_name)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "TOOL_NOT_FOUND", "message": "工具不存在"})
    row.enabled = data.enabled
    db.commit()
    return {"data": tool_dict(row)}
