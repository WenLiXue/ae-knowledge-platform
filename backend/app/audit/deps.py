"""审计相关 FastAPI 依赖。

管理类 API 统一要求管理员权限；保留该工厂函数让每个端点声明自己的审计动作。
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request, HTTPException, status
from ..auth.deps import get_current_user
from ..db.models.user import User
from .context import build_context


def require_admin_action(action: str) -> Callable:
    """要求管理员权限，并为被拒绝的管理操作写入 DENIED 审计事件。"""

    def dependency(request: Request, user: User = Depends(get_current_user)) -> User:
        if not user.is_admin:
            from . import service as audit_service
            audit_service.record_denied_independent(
                audit_service.denied_event(user=user, context=build_context(request), action=action)
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "ADMIN_REQUIRED", "message": "需要管理员权限"})
        return user

    return dependency
