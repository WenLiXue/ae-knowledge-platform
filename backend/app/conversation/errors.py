"""会话领域错误（DD-08 §3.3）。

code 为前端判断依据，detail 可展示。status 映射 HTTP 状态码。
正文/问题不进入日志（§3.5）。
"""

from __future__ import annotations


class ConversationError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
