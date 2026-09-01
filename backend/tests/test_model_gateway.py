"""Model Gateway 适配层测试（DD-19 Phase 3）。"""

import json

import httpx
import pytest

from app.model_gateway import (
    ChatRequest,
    EmbeddingRequest,
    GatewayError,
    OpenAICompatibleGateway,
    RerankRequest,
    create_gateway,
)


def _gateway(handler, *, retries: int = 0, **kwargs) -> OpenAICompatibleGateway:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatibleGateway(
        base_url="http://model.local/v1",
        api_key="sk-test",
        model="test-model",
        retries=retries,
        retry_backoff_seconds=0.0,
        http_client=client,
        **kwargs,
    )


def _chat_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "test-model",
            "choices": [{"message": {"content": "你好，来自模型"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


def test_chat_success() -> None:
    gw = _gateway(_chat_ok)
    resp = gw.chat(ChatRequest(model="test-model", messages=[{"role": "user", "content": "hi"}]))
    assert resp.content == "你好，来自模型"
    assert resp.model == "test-model"
    assert resp.usage.total_tokens == 15


def test_chat_schema_invalid_not_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "test-model", "choices": []})

    gw = _gateway(handler, retries=1)
    with pytest.raises(GatewayError) as excinfo:
        gw.chat(ChatRequest(model="test-model", messages=[]))
    assert excinfo.value.category == "SCHEMA"
    assert excinfo.value.retryable is False


def test_chat_auth_failed_not_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    gw = _gateway(handler, retries=1)
    with pytest.raises(GatewayError) as excinfo:
        gw.chat(ChatRequest(model="test-model", messages=[]))
    assert excinfo.value.category == "AUTH"
    assert excinfo.value.retryable is False


def test_429_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={})
        return _chat_ok(request)

    gw = _gateway(handler, retries=2)
    resp = gw.chat(ChatRequest(model="test-model", messages=[]))
    assert resp.content == "你好，来自模型"
    assert calls["n"] == 2


def test_5xx_retries_then_fails() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={})

    gw = _gateway(handler, retries=1)
    with pytest.raises(GatewayError) as excinfo:
        gw.chat(ChatRequest(model="test-model", messages=[]))
    assert excinfo.value.category == "PROVIDER"
    assert excinfo.value.retryable is True
    assert calls["n"] == 2


def test_network_error_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    gw = _gateway(handler, retries=0)
    with pytest.raises(GatewayError) as excinfo:
        gw.chat(ChatRequest(model="test-model", messages=[]))
    assert excinfo.value.category == "NETWORK"
    assert excinfo.value.retryable is True


def test_embed_success_and_count_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
            },
        )

    resp = _gateway(handler).embed(EmbeddingRequest(model="test-model", input=["a"]))
    assert resp.data[0].embedding == [0.1, 0.2, 0.3]

    def mismatch(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "m", "data": [{"index": 0, "embedding": [1.0]}]})

    with pytest.raises(GatewayError) as excinfo:
        _gateway(mismatch).embed(EmbeddingRequest(model="m", input=["a", "b"]))
    assert excinfo.value.code == "EMBEDDING_COUNT_MISMATCH"


def test_rerank_success() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = request.read()
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                ],
            },
        )

    resp = _gateway(handler).rerank(
        RerankRequest(
            model="test-model",
            query="q",
            documents=["a", "b"],
            instruction="rank direct evidence",
        )
    )
    assert [r.index for r in resp.results] == [1, 0]
    assert json.loads(seen["payload"])["instruction"] == "rank direct evidence"


def test_factory_unsupported_provider() -> None:
    from app.llm.runtime import ResolvedModel

    model = ResolvedModel(
        service_type="DOCUMENT_CLASSIFICATION",
        config_revision=1,
        model_config_id="m1",
        provider="google",
        protocol="google",  # 非 openai-compatible 协议 → factory 抛 UNSUPPORTED_PROVIDER
        base_url="http://x",
        model_name="m",
        api_key="k",
    )
    with pytest.raises(GatewayError) as excinfo:
        create_gateway(model)
    assert excinfo.value.code == "UNSUPPORTED_PROVIDER"
