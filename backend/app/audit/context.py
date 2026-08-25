"""审计请求上下文：request_id、来源、操作者快照（DD-17 §4、§8）。

- request_id 由中间件生成/透传（X-Request-ID），每个入口请求必填；
- source_ip 只取实际连接地址，或配置过的可信反向代理转发头，不能直接信任任意 X-Forwarded-For；
- 操作者快照在事件构造时固化，用户删除/改名后历史仍可读。
"""

from __future__ import annotations

import ipaddress
import uuid
from dataclasses import dataclass

from fastapi import Request

from ..core.config import get_settings
from ..db.models.user import User
from .policy import sanitize_text


@dataclass(frozen=True)
class AuditContext:
    request_id: str
    source_type: str
    source_ip: str | None
    user_agent: str | None
    trace_id: str | None


def _valid_ip(value: str | None) -> str | None:
    """返回可安全写入 INET 列的规范化 IP，非法值（如测试客户端 host）返回 None。"""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def _trusted_proxy_ip(request: Request) -> str | None:
    header_name = get_settings().audit_trusted_proxy_header.strip().lower()
    if not header_name:
        return None
    raw = request.headers.get(header_name)
    if not raw:
        return None
    # 取转发链最左的真实客户端地址，并去空格
    first = raw.split(",", 1)[0].strip()
    return _valid_ip(first)


def build_context(request: Request, *, source_type: str = "API") -> AuditContext:
    """从请求提取审计上下文。request_id 优先取中间件写入的 state。"""
    request_id = (
        getattr(request.state, "request_id", None)
        or request.headers.get("x-request-id")
        or uuid.uuid4().hex[:32]
    )
    source_ip = _trusted_proxy_ip(request)
    if source_ip is None and request.client is not None:
        source_ip = _valid_ip(request.client.host)
    user_agent = sanitize_text(request.headers.get("user-agent") or "") if request.headers.get("user-agent") else None
    return AuditContext(
        request_id=request_id[:64],
        source_type=source_type,
        source_ip=source_ip,
        user_agent=user_agent,
        trace_id=request.headers.get("x-trace-id"),
    )


def actor_from_user(user: User) -> dict:
    """登录用户的审计操作者快照。账号可为 None（飞书首次登录未设用户名）。"""
    return {
        "actor_type": "USER",
        "actor_user_id": str(user.id),
        "actor_key": None,
        "actor_name": user.display_name,
        "actor_account": user.username,
    }
