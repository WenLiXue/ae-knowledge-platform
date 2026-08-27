"""Agent run and approval endpoints."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import get_current_user
from ..db.models.conversation import AgentApproval, AgentRun
from ..db.session import get_db, SessionLocal
from ..db.models.user import User
from .approvals import decide_approval
from .tools.base import ToolError

router = APIRouter(prefix="/api/v1", tags=["agent"])


class ApprovalDecisionIn(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]


def _error(exc: ToolError) -> None:
    status = 409 if exc.code in {"APPROVAL_ALREADY_DECIDED", "APPROVAL_EXPIRED", "APPROVAL_STALE"} else 400
    raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})


@router.get("/answers/{answer_id}/approvals")
def list_approvals(answer_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.execute(
        select(AgentApproval, AgentRun)
        .join(AgentRun, AgentRun.id == AgentApproval.run_id)
        .where(AgentRun.answer_id == answer_id, AgentApproval.requested_by == user.id)
        .order_by(AgentApproval.created_at.desc())
    ).all()
    return {"data": {"items": [{
        "id": str(approval.id), "status": approval.status, "tool_name": approval.tool_name,
        "impact_summary": approval.impact_summary or {}, "expires_at": approval.expires_at,
        "decided_at": approval.decided_at,
    } for approval, _ in rows]}}


@router.post("/answers/{answer_id}/approvals/{approval_id}/decision")
def make_decision(
    answer_id: uuid.UUID,
    approval_id: uuid.UUID,
    data: ApprovalDecisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.execute(
        select(AgentApproval, AgentRun)
        .join(AgentRun, AgentRun.id == AgentApproval.run_id)
        .where(AgentApproval.id == approval_id, AgentRun.answer_id == answer_id)
    ).first()
    if row is None or row[0].requested_by != user.id:
        raise HTTPException(status_code=404, detail={"code": "APPROVAL_NOT_FOUND", "message": "确认请求不存在"})
    try:
        result = decide_approval(SessionLocal, approval_id=str(approval_id), user_id=str(user.id), decision=data.decision)
    except ToolError as exc:
        _error(exc)
    return {"data": result}
