"""Model Gateway 领域契约（DD-19 §7）。

- ChatRequest/ChatResponse：对话补全；
- EmbeddingRequest/EmbeddingResponse：向量化；
- RerankRequest/RerankResponse：相关性重排。
- ModelGateway 协议：屏蔽供应商协议差异，统一超时、错误、用量与响应校验。
正文、Prompt、Token、密钥不进入日志（§7/§17）。
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class GatewayTool(BaseModel):
    """Provider-neutral tool description; model output is not authorization."""

    name: str
    description: str
    parameters: dict[str, Any]


class GatewayToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ChatRequest(BaseModel):
    model: str
    messages: list[dict]
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    tools: list[GatewayTool] = Field(default_factory=list)
    tool_choice: Literal["none", "auto", "required"] | str = "none"
    # Provider-neutral structured output hint. OpenAI-compatible providers
    # accept {"type": "json_object"}; providers that ignore it still get
    # schema validation at the caller.
    response_format: dict[str, Any] | None = None


class ChatUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    model: str
    content: str = ""
    tool_calls: list[GatewayToolCall] = Field(default_factory=list)
    usage: ChatUsage = Field(default_factory=ChatUsage)
    raw: dict | None = None


class EmbeddingRequest(BaseModel):
    model: str
    input: list[str]


class EmbeddingData(BaseModel):
    index: int
    embedding: list[float]


class EmbeddingUsage(BaseModel):
    prompt_tokens: int = 0
    total_tokens: int = 0


class EmbeddingResponse(BaseModel):
    model: str
    data: list[EmbeddingData]
    usage: EmbeddingUsage = Field(default_factory=EmbeddingUsage)
    raw: dict | None = None


class RerankRequest(BaseModel):
    model: str
    query: str
    documents: list[str]
    top_n: int | None = None


class RerankResult(BaseModel):
    index: int
    relevance_score: float
    document: str | None = None


class RerankResponse(BaseModel):
    model: str
    results: list[RerankResult]
    raw: dict | None = None


class ModelGateway(Protocol):
    """供应商无关的模型调用协议。"""

    def chat(self, request: ChatRequest) -> ChatResponse: ...
    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...
    def rerank(self, request: RerankRequest) -> RerankResponse: ...
