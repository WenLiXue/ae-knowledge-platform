"""FastAPI 依赖：当前用户与会话。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.context import set_user_id
from ..db.models.user import User
from ..db.session import get_db
from ..feishu_auth.factory import get_feishu_oauth_client
from . import feishu as auth_feishu
from . import sessions


def _session_token(request: Request) -> str | None:
    return request.cookies.get(get_settings().session_cookie_name)


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """必需登录：无有效会话返回 401 AUTH_REQUIRED。"""
    user = sessions.get_user_by_session(db, _session_token(request))
    if user is None or user.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_REQUIRED", "message": "未登录或会话已失效"},
        )
    # 供访问日志/异常日志关联操作者（request.state 跨线程可靠，ContextVar 供请求线程内日志）
    request.state.user_id = str(user.id)
    set_user_id(str(user.id))
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """必需管理员：非管理员返回 403 FORBIDDEN。"""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "需要管理员权限"},
        )
    return user


def get_optional_user(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    """可选登录：有会话则返回用户，否则 None（不报错）。"""
    user = sessions.get_user_by_session(db, _session_token(request))
    request.state.user_id = str(user.id) if user else None
    if user:
        set_user_id(str(user.id))
    return user


def get_optional_feishu_token(
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> str | None:
    """可选返回当前用户可用的飞书 user_access_token；未登录/未绑定则 None。"""
    if user is None:
        return None
    return auth_feishu.get_user_access_token(db, user.id, get_feishu_oauth_client())
