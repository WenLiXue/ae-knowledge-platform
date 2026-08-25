"""审计相关 FastAPI 依赖（DD-17 §6.1、§9）。

管理员权限失败时写入 DENIED 审计事件（独立短事务），不执行领域命令、不泄露目标详情。
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..auth.deps import get_current_user
from ..db.models.user import User
from ..db.session import get_db
from .context import build_context
from .service import denied_event, record_denied_independent


def require_admin_action(action: str) -> Callable:
    """需要管理员权限，并在权限失败时写入对应动作的 DENIED 审计。"""

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> User:
        if not user.is_admin:
            record_denied_independent(denied_event(user=user, context=build_context(request), action=action))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "需要管理员权限"},
            )
        return user

    return dependency
