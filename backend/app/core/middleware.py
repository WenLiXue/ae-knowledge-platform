"""请求上下文与访问日志中间件。

- 为每个 HTTP 请求生成/透传 request_id，写入请求上下文并回填 `X-Request-ID` 响应头；
- 统一记录一条访问日志（方法/路径/脱敏 query/状态/耗时/request_id/user_id）；
- query 中 token/密钥/用户输入类参数一律脱敏（DD-12 最小暴露，不落问题正文）。
"""

from __future__ import annotations

import logging
import time
import uuid
from urllib.parse import parse_qsl, quote

from starlette.middleware.base import BaseHTTPMiddleware

from . import context

logger = logging.getLogger("app.api.access")

# 访问日志中需要脱敏的 query 参数（token/密钥/用户输入正文等）
_SENSITIVE_QUERY_PARAMS = {
    "token", "code", "state", "secret", "api_key", "signature", "access_token",
    "search_key", "q", "query",
}
_MASK = "***"


def _sanitized_query(query_string: str) -> str | None:
    """query 中敏感参数值替换为 ***（字面量，不转义）；空 query 返回 None（不进 JSON）。"""
    if not query_string:
        return None
    pairs = [(k, v) for k, v in parse_qsl(query_string, keep_blank_values=True)]
    parts = []
    for key, value in pairs:
        if key in _SENSITIVE_QUERY_PARAMS:
            parts.append(f"{quote(key)}={_MASK}")
        else:
            parts.append(f"{quote(key)}={quote(value)}")
    return "&".join(parts)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """注入 request 上下文 + 记录访问日志 + 回写 X-Request-ID。"""

    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        # 同时写 request.state，供审计事件（DD-17 §4.2）读取同一关联号
        request.state.request_id = request_id
        token = context.set_request_context(
            context.RequestContext(
                request_id=request_id,
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
        )
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "http_request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "query": _sanitized_query(request.url.query),
                    "status": status,
                    "duration_ms": round(duration_ms, 3),
                    "user_id": getattr(request.state, "user_id", None),
                },
            )
            context.reset_request_context(token)
