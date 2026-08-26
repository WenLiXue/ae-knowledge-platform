"""Agent 类型化错误（DD-21 §15）。

错误码稳定，retryable 决定 Worker 是否重试。错误摘要必须脱敏，
不记录密钥、完整提示词、整段文档或用户敏感信息。
"""

from __future__ import annotations

# 稳定错误码
AGENT_INPUT_INVALID = "AGENT_INPUT_INVALID"
AGENT_ROUTE_INVALID = "AGENT_ROUTE_INVALID"
AGENT_STEP_LIMIT_EXCEEDED = "AGENT_STEP_LIMIT_EXCEEDED"
AGENT_TIMEOUT = "AGENT_TIMEOUT"
AGENT_CANCELED = "AGENT_CANCELED"
RETRIEVAL_UNAVAILABLE = "RETRIEVAL_UNAVAILABLE"
EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
CITATION_VALIDATION_FAILED = "CITATION_VALIDATION_FAILED"
MEMORY_UPDATE_FAILED = "MEMORY_UPDATE_FAILED"
CHECKPOINT_UNAVAILABLE = "CHECKPOINT_UNAVAILABLE"
GENERATION_FAILED = "GENERATION_FAILED"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


class AgentError(Exception):
    """Agent 领域错误。category/code/retryable 映射到现有 Worker 语义。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        category: str = "AGENT",
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.category = category


class AgentCanceled(AgentError):
    """用户已取消：不继续生成，状态 CANCELED。"""

    def __init__(self) -> None:
        super().__init__(AGENT_CANCELED, "用户已取消回答", retryable=False, category="AGENT")
