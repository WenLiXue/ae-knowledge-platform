"""检索服务领域错误（DD-19 §12）。

category 对齐业务可观测：VALIDATION（过滤条件非法/配置非法，不可重试）、
PROVIDER（外部依赖失败，由检索流程按降级规则处理或转为整体失败）。
稳定 code 供日志与降级判断；正文/问题不进入日志。
"""

from __future__ import annotations


class RetrievalError(Exception):
    def __init__(
        self,
        category: str,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message
        self.retryable = retryable
