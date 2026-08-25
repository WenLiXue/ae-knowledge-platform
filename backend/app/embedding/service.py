"""文档向量化服务（DD-19 §11.1）。

- 按 batch_size 分批调用 gateway.embed；
- 校验返回数量 == 输入数量、批次内与跨批次维度一致、所有值为有限数值；
- 任一批次失败/校验失败都抛 EmbeddingError，版本不得进入 INDEX；
- 不落 PostgreSQL（向量写隔离索引），正文/向量不进入日志。
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

from ..model_gateway.base import EmbeddingRequest
from ..model_gateway.errors import GatewayError


class EmbeddingError(Exception):
    """向量化领域错误。category/code 稳定，retryable 决定任务是否重试。"""

    def __init__(self, category: str, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class EmbeddingItem:
    chunk_id: uuid.UUID
    ordinal: int
    content: str
    embedding: list[float]


@dataclass(frozen=True)
class EmbeddingRunResult:
    items: list[EmbeddingItem]
    dimension: int
    token_usage: dict = field(default_factory=dict)


def _as_float_vector(vec) -> list[float]:
    if not isinstance(vec, list) or not vec:
        raise EmbeddingError("SCHEMA", "EMBED_EMPTY_VECTOR", "向量为空", retryable=False)
    out: list[float] = []
    for x in vec:
        if not isinstance(x, (int, float)):
            raise EmbeddingError("SCHEMA", "EMBED_NON_FINITE", "向量包含非数值元素", retryable=False)
        value = float(x)
        if not math.isfinite(value):
            raise EmbeddingError("SCHEMA", "EMBED_NON_FINITE", "向量包含非有限数值", retryable=False)
        out.append(value)
    return out


def embed_chunks(
    chunks,
    *,
    gateway,
    model_name: str,
    batch_size: int = 32,
) -> EmbeddingRunResult:
    """分批向量化并严格校验。chunks 需提供 id/ordinal/content（DocumentChunk 或同构对象）。"""
    if not chunks:
        raise EmbeddingError("VALIDATION", "EMBED_EMPTY", "没有可向量化的切片", retryable=False)
    if batch_size <= 0:
        batch_size = 32

    items: list[EmbeddingItem] = []
    expected_dim: int | None = None
    usage = {"prompt_tokens": 0, "total_tokens": 0}

    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        texts = [c.content for c in batch]
        try:
            resp = gateway.embed(EmbeddingRequest(model=model_name, input=texts))
        except GatewayError as exc:
            raise EmbeddingError(exc.category, exc.code, exc.message, retryable=exc.retryable) from exc

        if len(resp.data) != len(batch):
            raise EmbeddingError(
                "SCHEMA", "EMBED_COUNT_MISMATCH", "向量数量与切片数量不一致", retryable=False
            )
        ordered = sorted(resp.data, key=lambda d: d.index)
        for chunk, data in zip(batch, ordered):
            vec = _as_float_vector(data.embedding)
            dim = len(vec)
            if expected_dim is None:
                expected_dim = dim
            elif dim != expected_dim:
                raise EmbeddingError(
                    "SCHEMA", "EMBED_DIM_MISMATCH", "向量维度跨批次不一致", retryable=False
                )
            items.append(
                EmbeddingItem(chunk_id=chunk.id, ordinal=chunk.ordinal, content=chunk.content, embedding=vec)
            )
        if resp.usage is not None:
            usage["prompt_tokens"] += resp.usage.prompt_tokens
            usage["total_tokens"] += resp.usage.total_tokens

    if expected_dim is None:
        raise EmbeddingError("SCHEMA", "EMBED_DIM_MISSING", "未获得向量维度", retryable=False)
    return EmbeddingRunResult(items=items, dimension=expected_dim, token_usage=usage)
