"""文档向量化服务测试（DD-19 §11.1）。

覆盖：分批成功与跨批次维度一致、返回数量不匹配、维度不一致、非有限数值、
空输入、批大小边界。
"""

from __future__ import annotations

import math
import uuid

import pytest

from app.embedding.service import EmbeddingError, embed_chunks
from app.model_gateway.base import EmbeddingData, EmbeddingRequest, EmbeddingResponse, EmbeddingUsage


class FakeEmbeddingGateway:
    """确定性假网关：按输入生成固定维度向量；可注入返回数量/维度/数值异常。"""

    def __init__(self, *, dim: int = 4, count_offset: int = 0, bad_index: int | None = None, bad_value: float | None = None):
        self.dim = dim
        self.count_offset = count_offset
        self.bad_index = bad_index
        self.bad_value = bad_value
        self.calls: list[EmbeddingRequest] = []

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.calls.append(request)
        data = []
        for i, _ in enumerate(request.input):
            vec = [float(i + 1) / 10.0 for _ in range(self.dim)]
            if self.bad_index == i:
                vec[0] = self.bad_value if self.bad_value is not None else float("nan")
            data.append(EmbeddingData(index=i, embedding=vec))
        if self.count_offset:
            data = data[: len(data) - self.count_offset] if len(data) > self.count_offset else data
        return EmbeddingResponse(
            model=request.model,
            data=data,
            usage=EmbeddingUsage(prompt_tokens=len(request.input), total_tokens=len(request.input)),
        )


def _chunk(seq: int) -> object:
    class _C:
        pass
    c = _C()
    c.id = uuid.uuid4()
    c.ordinal = seq
    c.content = f"第 {seq} 段正文内容。"
    return c


def test_embed_chunks_batches_and_validates_dimension() -> None:
    chunks = [_chunk(i) for i in range(5)]
    gateway = FakeEmbeddingGateway(dim=4)
    result = embed_chunks(chunks, gateway=gateway, model_name="emb", batch_size=2)
    assert result.dimension == 4
    assert len(result.items) == 5
    # 分批：ceil(5/2)=3 次调用
    assert len(gateway.calls) == 3
    assert all(len(c.input) <= 2 for c in gateway.calls)
    assert all(len(it.embedding) == 4 for it in result.items)
    # 顺序与 ordinal 对应
    assert [it.ordinal for it in result.items] == list(range(5))
    assert result.token_usage["total_tokens"] == 5


def test_embed_chunks_can_use_contextual_text_without_changing_citations() -> None:
    chunks = [_chunk(1)]
    gateway = FakeEmbeddingGateway(dim=4)
    result = embed_chunks(
        chunks,
        gateway=gateway,
        model_name="emb",
        text_builder=lambda chunk: f"Section: troubleshooting\nContent: {chunk.content}",
    )
    assert gateway.calls[0].input[0].startswith("Section: troubleshooting")
    assert result.items[0].content == chunks[0].content


def test_embed_count_mismatch_fails() -> None:
    chunks = [_chunk(i) for i in range(3)]
    gateway = FakeEmbeddingGateway(dim=4, count_offset=1)
    with pytest.raises(EmbeddingError) as exc:
        embed_chunks(chunks, gateway=gateway, model_name="emb", batch_size=10)
    assert exc.value.code == "EMBED_COUNT_MISMATCH"
    assert exc.value.retryable is False


def test_embed_dimension_mismatch_across_batches_fails() -> None:
    chunks = [_chunk(i) for i in range(4)]
    gateway = _DimChangingGateway(batch_dim={0: 4, 1: 8})
    with pytest.raises(EmbeddingError) as exc:
        embed_chunks(chunks, gateway=gateway, model_name="emb", batch_size=2)
    assert exc.value.code == "EMBED_DIM_MISMATCH"


def test_embed_non_finite_value_fails() -> None:
    chunks = [_chunk(i) for i in range(2)]
    gateway = FakeEmbeddingGateway(dim=4, bad_index=1, bad_value=float("inf"))
    with pytest.raises(EmbeddingError) as exc:
        embed_chunks(chunks, gateway=gateway, model_name="emb", batch_size=10)
    assert exc.value.code == "EMBED_NON_FINITE"


def test_embed_empty_input_fails() -> None:
    with pytest.raises(EmbeddingError) as exc:
        embed_chunks([], gateway=FakeEmbeddingGateway(), model_name="emb")
    assert exc.value.code == "EMBED_EMPTY"


def test_embed_validates_finite_but_accepts_normal_floats() -> None:
    chunks = [_chunk(i) for i in range(2)]
    gateway = FakeEmbeddingGateway(dim=4)
    result = embed_chunks(chunks, gateway=gateway, model_name="emb", batch_size=1)
    assert all(math.isfinite(x) for it in result.items for x in it.embedding)


class _DimChangingGateway:
    """按调用序号返回不同维度的假网关（验证跨批次维度不一致）。"""

    def __init__(self, batch_dim: dict[int, int]):
        self.batch_dim = batch_dim
        self._calls = 0

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        dim = self.batch_dim.get(self._calls, 4)
        self._calls += 1
        data = [
            EmbeddingData(index=i, embedding=[0.1 * i for _ in range(dim)])
            for i in range(len(request.input))
        ]
        return EmbeddingResponse(model=request.model, data=data, usage=EmbeddingUsage())
