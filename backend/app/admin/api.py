"""管理员能力：全量会话只读审阅与用户状态管理。"""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import service as audit_service
from ..audit.context import build_context
from ..audit.deps import require_admin_action
from ..conversation import service as conversation_service
from ..db.models.auth import ExternalCredential, ExternalIdentity
from ..db.models.conversation import Conversation
from ..db.models.user import User
from ..db.session import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

class UserUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    status: str | None = Field(default=None, pattern="^(ACTIVE|DISABLED)$")
    is_admin: bool | None = None

def _user_out(user: User, account_id: str | None = None, identity: ExternalIdentity | None = None) -> dict:
    snapshot = identity.profile_snapshot if identity else None
    avatar_url = snapshot.get("avatar_url") if isinstance(snapshot, dict) else None
    return {"id": str(user.id), "username": user.username or account_id, "display_name": user.display_name,
            "email": user.email, "status": user.status, "is_admin": user.is_admin,
            "created_source": user.created_source, "created_at": user.created_at, "avatar_url": avatar_url}

@router.get("/users")
def list_users(request: Request, keyword: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0,
               db: Session = Depends(get_db), admin: User = Depends(require_admin_action("user.query"))):
    query = select(User, ExternalIdentity).outerjoin(
        ExternalIdentity,
        (ExternalIdentity.user_id == User.id) & (ExternalIdentity.provider == "FEISHU")
    )
    if keyword:
        term = f"%{keyword.strip()}%"
        query = query.where((User.username.ilike(term)) | (User.display_name.ilike(term)) | (User.email.ilike(term)))
    if status in {"ACTIVE", "DISABLED"}:
        query = query.where(User.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(db.execute(query.order_by(User.created_at.desc()).offset(max(offset, 0)).limit(min(max(limit, 1), 200))).all())
    audit_service.record_success(db, audit_service.success_event(
        user=admin, context=build_context(request), action="user.query", summary="查看用户列表",
        target_type="USER", metadata={"count": len(rows), "total": total},
    ))
    db.commit()
    return {"data": {"items": [_user_out(user, identity.external_user_id if identity else None, identity) for user, identity in rows], "total": total}}

@router.patch("/users/{user_id}")
def update_user(request: Request, user_id: uuid.UUID, data: UserUpdateIn, db: Session = Depends(get_db), admin: User = Depends(require_admin_action("user.update"))):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"})
    if user.id == admin.id and data.status == "DISABLED":
        raise HTTPException(400, detail={"code": "SELF_DISABLE_FORBIDDEN", "message": "不能禁用当前管理员账号"})
    if user.created_source == "SYSTEM" and (data.status is not None or data.is_admin is not None):
        raise HTTPException(400, detail={"code": "SYSTEM_ACCOUNT_PROTECTED", "message": "系统账号不可修改状态或角色"})
    before = {"display_name": user.display_name, "status": user.status, "is_admin": user.is_admin}
    if data.display_name is not None:
        user.display_name = data.display_name.strip() or user.display_name
    if data.status is not None:
        user.status = data.status
    if data.is_admin is not None:
        user.is_admin = data.is_admin
    changes = audit_service.build_changes({k: (before[k], getattr(user, k)) for k in before})
    changed_fields = {item["field"] for item in changes}
    if changed_fields == {"is_admin"}:
        action = "user.role.change"
    elif changed_fields == {"status"} and user.status == "DISABLED":
        action = "user.disable"
    elif changed_fields == {"status"} and user.status == "ACTIVE":
        action = "user.enable"
    else:
        action = "user.update"
    audit_service.record_success(db, audit_service.success_event(
        user=admin, context=build_context(request), action=action, summary="更新用户管理属性",
        target_type="USER", target_id=str(user.id), target_name=user.display_name, changes=changes,
    ))
    db.commit()
    db.refresh(user)
    return {"data": _user_out(user)}


@router.get("/users/{user_id}")
def get_user_detail(request: Request, user_id: uuid.UUID, db: Session = Depends(get_db), admin: User = Depends(require_admin_action("user.view"))):
    row = db.execute(
        select(User, ExternalIdentity, ExternalCredential)
        .outerjoin(ExternalIdentity, (ExternalIdentity.user_id == User.id) & (ExternalIdentity.provider == "FEISHU"))
        .outerjoin(ExternalCredential, ExternalCredential.identity_id == ExternalIdentity.id)
        .where(User.id == user_id)
    ).first()
    if row is None:
        raise HTTPException(404, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"})
    user, identity, credential = row
    audit_service.record_success(db, audit_service.success_event(
        user=admin, context=build_context(request), action="user.view", summary="查看用户详情",
        target_type="USER", target_id=str(user.id), target_name=user.display_name,
    ))
    db.commit()
    return {"data": {
        **_user_out(user, identity.external_user_id if identity else None, identity),
        "feishu": {
            "bound": identity is not None and identity.binding_status == "BOUND",
            "provider": identity.provider if identity else None,
            "tenant_key": identity.tenant_key if identity else None,
            "external_user_id": identity.external_user_id if identity else None,
            "open_id": identity.open_id if identity else None,
            "union_id": identity.union_id if identity else None,
            "bound_at": identity.bound_at if identity else None,
            "access_expires_at": credential.access_expires_at if credential else None,
        },
    }}

@router.get("/conversations")
def list_all_conversations(request: Request, keyword: str | None = None, limit: int = 50, offset: int = 0,
                           db: Session = Depends(get_db), admin: User = Depends(require_admin_action("conversation.admin.list"))):
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
    audit_service.record_success(db, audit_service.success_event(
        user=admin, context=build_context(request), action="conversation.admin.list", summary="查看全部会话列表",
        target_type="CONVERSATION", metadata={"count": len(items), "total": total},
    ))
    db.commit()
    return {"data": {"items": items, "total": total}}

@router.get("/conversations/{conversation_id}")
def get_all_conversation_messages(conversation_id: uuid.UUID, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin_action("conversation.admin.view"))):
    row = db.execute(select(Conversation, User).join(User, User.id == Conversation.user_id).where(Conversation.id == conversation_id, Conversation.status != "DELETED")).first()
    if row is None:
        raise HTTPException(404, detail={"code": "CONVERSATION_NOT_FOUND", "message": "会话不存在"})
    conversation, owner = row
    messages = conversation_service.list_messages(db, owner, conversation_id)
    audit_service.record_success(db, audit_service.success_event(
        user=admin, context=build_context(request), action="conversation.admin.view", summary="查看会话内容",
        target_type="CONVERSATION", target_id=str(conversation.id), target_name=conversation.title,
        metadata={"message_count": len(messages), "owner_id": str(owner.id)},
    ))
    db.commit()
    return {"data": {"conversation": {"id": str(conversation.id), "title": conversation.title,
             "status": conversation.status, "filters": conversation.filters_snapshot or {},
             "last_message_at": conversation.last_message_at, "created_at": conversation.created_at,
             "owner": {"id": str(owner.id), "username": owner.username, "display_name": owner.display_name}},
             "messages": [m.model_dump(mode="json") for m in messages]}}
