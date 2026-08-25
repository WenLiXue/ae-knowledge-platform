"""Model Gateway 稳定错误分类（DD-19 §7）。

- category 对齐业务可观测：NETWORK / RATE_LIMIT / AUTH / VALIDATION / SCHEMA / PROVIDER；
- 只有 NETWORK、RATE_LIMIT、临时 5xx（PROVIDER retryable=True）允许有限重试；
- 400/401/403、Schema 错误不做无意义重试。
"""

from __future__ import annotations


class GatewayError(Exception):
    """网关错误。code 为稳定错误码，供日志与降级判断。"""

    def __init__(
        self,
        category: str,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status: int | None = None,
    ):
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status = status
