"""审计相关 FastAPI 依赖。

系统管理已统一改为登录用户可访问；保留该工厂函数只是为了兼容既有
API 声明和审计动作名称。
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends
from sqlalchemy.orm import Session

from ..auth.deps import get_current_user
from ..db.models.user import User


def require_admin_action(action: str) -> Callable:
    """兼容旧声明：只要求登录，不再检查管理员角色。"""

    def dependency(user: User = Depends(get_current_user)) -> User:
        return user

    return dependency
