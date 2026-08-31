"""管理员能力：全量会话只读审阅与用户状态管理。"""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.deps import get_current_admin
from ..conversation import service as conversation_service
from ..db.models.conversation import Conversation
from ..db.models.user import User
from ..db.session import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

class UserUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    status: str | None = Field(default=None, pattern="^(ACTIVE|DISABLED)$")
    is_admin: bool | None = None

def _user_out(user: User) -> dict:
    return {"id": str(user.id), "username": user.username, "display_name": user.display_name,
            "email": user.email, "status": user.status, "is_admin": user.is_admin,
            "created_source": user.created_source, "created_at": user.created_at}

@router.get("/users")
def list_users(keyword: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0,
               db: Session = Depends(get_db), _: User = Depends(get_current_admin)):
    query = select(User)
    if keyword:
        term = f"%{keyword.strip()}%"
        query = query.where((User.username.ilike(term)) | (User.display_name.ilike(term)) | (User.email.ilike(term)))
    if status in {"ACTIVE", "DISABLED"}:
        query = query.where(User.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(User.created_at.desc()).offset(max(offset, 0)).limit(min(max(limit, 1), 200))).scalars()
    return {"data": {"items": [_user_out(user) for user in rows], "total": total}}

@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, data: UserUpdateIn, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"})
    if user.id == admin.id and data.status == "DISABLED":
        raise HTTPException(400, detail={"code": "SELF_DISABLE_FORBIDDEN", "message": "不能禁用当前管理员账号"})
    if data.display_name is not None:
        user.display_name = data.display_name.strip() or user.display_name
    if data.status is not None:
        user.status = data.status
    if data.is_admin is not None:
        user.is_admin = data.is_admin
    db.commit(); db.refresh(user)
    return {"data": _user_out(user)}

@router.get("/conversations")
def list_all_conversations(keyword: str | None = None, limit: int = 50, offset: int = 0,
                           db: Session = Depends(get_db), _: User = Depends(get_current_admin)):
    query = select(Conversation, User).join(User, User.id == Conversation.user_id).where(Conversation.status != "DELETED")
    if keyword:
        term = f"%{keyword.strip()}%"
        query = query.where((Conversation.title.ilike(term)) | (User.username.ilike(term)) | (User.display_name.ilike(term)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc()).offset(max(offset, 0)).limit(min(max(limit, 1), 200))).all()
    items = [{"id": str(c.id), "title": c.title, "status": c.status, "filters": c.filters_snapshot or {},
              "last_message_at": c.last_message_at, "created_at": c.created_at,
              "owner": {"id": str(u.id), "username": u.username, "display_name": u.display_name}}
             for c, u in rows]
    return {"data": {"items": items, "total": total}}

@router.get("/conversations/{conversation_id}")
def get_all_conversation_messages(conversation_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(get_current_admin)):
    row = db.execute(select(Conversation, User).join(User, User.id == Conversation.user_id).where(Conversation.id == conversation_id, Conversation.status != "DELETED")).first()
    if row is None:
        raise HTTPException(404, detail={"code": "CONVERSATION_NOT_FOUND", "message": "会话不存在"})
    conversation, owner = row
    messages = conversation_service.list_messages(db, owner, conversation_id)
    return {"data": {"conversation": {"id": str(conversation.id), "title": conversation.title,
             "status": conversation.status, "filters": conversation.filters_snapshot or {},
             "last_message_at": conversation.last_message_at, "created_at": conversation.created_at,
             "owner": {"id": str(owner.id), "username": owner.username, "display_name": owner.display_name}},
             "messages": [m.model_dump(mode="json") for m in messages]}}
