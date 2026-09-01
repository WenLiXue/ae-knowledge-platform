"""供应商原始响应严格校验（DD-19 §7）。

只做“线上格式”的 Pydantic 校验，任何字段缺失/类型不符都会在调用层
转为 SCHEMA 错误（不可重试），不会把供应商脏数据透传给业务。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError  # noqa: F401  # 供调用方复用


class OpenAIChatChoice(BaseModel):
    message: dict


class OpenAIChatUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenAIChatResponse(BaseModel):
    model: str
    choices: list[OpenAIChatChoice]
    usage: OpenAIChatUsage | None = None


class OpenAIEmbeddingItem(BaseModel):
    index: int
    embedding: list[float]


class OpenAIEmbeddingUsage(BaseModel):
    prompt_tokens: int = 0
    total_tokens: int = 0


class OpenAIEmbeddingResponse(BaseModel):
    model: str
    data: list[OpenAIEmbeddingItem]
    usage: OpenAIEmbeddingUsage | None = None


class OpenAIRerankResult(BaseModel):
    index: int
    relevance_score: float
    document: str | None = None


class OpenAIRerankResponse(BaseModel):
    # SiliconFlow's /rerank response omits the model field although the
    # OpenAI-compatible contract commonly includes it.
    model: str = ""
    results: list[OpenAIRerankResult]


def _map_usage(usage: BaseModel | None) -> dict:
    if usage is None:
        return {}
    return usage.model_dump()
