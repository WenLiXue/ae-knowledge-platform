"""登录会话：Cookie 只存随机会话令牌，数据库只存令牌哈希（DD-12 §2）。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.auth import LoginSession
from ..db.models.user import User


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def create_session(session: Session, user_id, ttl_hours: int) -> str:
    """创建会话，返回明文令牌（写 Cookie 用）；库内只存哈希。"""
    raw = secrets.token_urlsafe(32)
    session.add(
        LoginSession(
            user_id=user_id,
            token_hash=_hash(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
        )
    )
    return raw


def get_user_by_session(session: Session, raw_token: str | None) -> User | None:
    if not raw_token:
        return None
    now = datetime.now(timezone.utc)
    row = session.execute(
        select(LoginSession).where(
            LoginSession.token_hash == _hash(raw_token),
            LoginSession.revoked_at.is_(None),
            LoginSession.expires_at > now,
        )
    ).scalars().first()
    if row is None:
        return None
    row.last_seen_at = now
    session.flush()
    return session.get(User, row.user_id)


def revoke_session(session: Session, raw_token: str | None) -> None:
    if not raw_token:
        return
    row = session.execute(
        select(LoginSession).where(LoginSession.token_hash == _hash(raw_token))
    ).scalars().first()
    if row is not None:
        row.revoked_at = datetime.now(timezone.utc)
        session.flush()
