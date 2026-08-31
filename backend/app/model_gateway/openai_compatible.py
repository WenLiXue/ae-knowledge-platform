"""OpenAI-compatible Model Gateway 适配器（DD-19 §7）。

- 统一超时（connect/read/total）、有限重试（网络、429、临时 5xx）；
- 400/401/403、Schema 错误不做重试，转稳定错误码；
- 严格校验供应商响应，脏数据不透传业务；
- 日志只含 request_id/model/耗时/用量/稳定错误码，不含正文、Prompt、Token、密钥。
"""

from __future__ import annotations

import logging
import json
import time
import uuid
from collections.abc import Iterator

import httpx

from .base import (
    ChatRequest,
    ChatResponse,
    ChatUsage,
    GatewayToolCall,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
    RerankRequest,
    RerankResponse,
)
from .errors import GatewayError
from .schemas import (
    OpenAIChatResponse,
    OpenAIEmbeddingResponse,
    OpenAIRerankResponse,
    ValidationError,
)

logger = logging.getLogger(__name__)

_ENDPOINTS = {
    "chat": "chat/completions",
    "embedding": "embeddings",
    "rerank": "rerank",
}


def _request_id() -> str:
    return uuid.uuid4().hex


class OpenAICompatibleGateway:
    """OpenAI-compatible 协议适配器。provider=openai-compatible。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        total_timeout: float = 300.0,
        retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        http_client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.total_timeout = total_timeout
        self.retries = retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._http_client = http_client

    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=self.total_timeout)
        return self._http_client

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, endpoint: str, payload: dict, *, request_id: str) -> dict:
        """POST 并做有限重试。非 200 按状态码映射稳定错误。"""
        url = f"{self.base_url}/{endpoint}"
        last_error: GatewayError | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self._client().post(url, json=payload, headers=self._headers())
            except httpx.TimeoutException as exc:
                last_error = GatewayError("NETWORK", "TIMEOUT", "模型调用超时", retryable=True)
            except httpx.TransportError as exc:
                last_error = GatewayError("NETWORK", "TRANSPORT_ERROR", "模型调用网络错误", retryable=True)
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise GatewayError("SCHEMA", "INVALID_JSON", "模型返回非法 JSON", retryable=False) from exc
                if response.status_code in (401, 403):
                    raise GatewayError("AUTH", "AUTH_FAILED", "模型凭据无效或无权访问", retryable=False, status=response.status_code)
                if response.status_code in (400, 404, 422):
                    raise GatewayError("VALIDATION", "BAD_REQUEST", f"模型请求被拒绝（{response.status_code}）", retryable=False, status=response.status_code)
                # 429 / 5xx：可重试
                if response.status_code == 429:
                    last_error = GatewayError("RATE_LIMIT", "RATE_LIMIT", "模型调用触发限流", retryable=True, status=429)
                else:
                    last_error = GatewayError("PROVIDER", f"PROVIDER_{response.status_code}", "模型服务异常", retryable=True, status=response.status_code)
            if attempt < self.retries:
                time.sleep(self.retry_backoff_seconds * (2 ** attempt))
                continue
            break
        assert last_error is not None
        raise last_error

    def chat(self, request: ChatRequest) -> ChatResponse:
        request_id = _request_id()
        started = time.monotonic()
        payload = {"model": request.model, "messages": request.messages}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.response_format is not None:
            payload["response_format"] = request.response_format
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = request.tool_choice
        data = self._post(_ENDPOINTS["chat"], payload, request_id=request_id)
        try:
            validated = OpenAIChatResponse.model_validate(data)
        except ValidationError as exc:
            raise GatewayError("SCHEMA", "CHAT_SCHEMA_INVALID", "模型响应不符合对话协议", retryable=False) from exc
        if not validated.choices:
            raise GatewayError("SCHEMA", "CHAT_EMPTY", "模型返回空内容", retryable=False)
        message = validated.choices[0].message
        content = str(message.get("content") or "")
        tool_calls: list[GatewayToolCall] = []
        for raw_call in message.get("tool_calls") or []:
            try:
                function = raw_call.get("function") or {}
                raw_arguments = function.get("arguments") or {}
                arguments = (
                    json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                )
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must be object")
                tool_calls.append(
                    GatewayToolCall(
                        id=str(raw_call.get("id") or _request_id()),
                        name=str(function["name"]),
                        arguments=arguments,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise GatewayError("SCHEMA", "TOOL_CALL_SCHEMA_INVALID", "模型工具调用格式无效", retryable=False) from exc
        if not content and not tool_calls:
            raise GatewayError("SCHEMA", "CHAT_EMPTY", "模型返回空内容", retryable=False)
        usage = validated.usage
        response = ChatResponse(
            model=validated.model,
            content=content,
            tool_calls=tool_calls,
            usage=ChatUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
            ),
            raw=data,
        )
        logger.debug(
            "gateway_chat",
            extra={
                "request_id": request_id,
                "model": request.model,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            },
        )
        return response

    def stream_chat(self, request: ChatRequest) -> Iterator[str]:
        """Stream assistant text deltas from an OpenAI-compatible endpoint.

        The normal ``chat`` path remains the authoritative structured-output
        path. This method is intentionally a small transport primitive: it
        yields only text deltas and leaves persistence, cancellation and final
        schema validation to the caller.
        """
        request_id = _request_id()
        payload = {"model": request.model, "messages": request.messages, "stream": True}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.response_format is not None:
            payload["response_format"] = request.response_format
        url = f"{self.base_url}/{_ENDPOINTS['chat']}"
        try:
            with self._client().stream("POST", url, json=payload, headers=self._headers()) as response:
                if response.status_code != 200:
                    # Reuse stable status handling without consuming partial
                    # data; callers get the same GatewayError categories.
                    if response.status_code in (401, 403):
                        raise GatewayError("AUTH", "AUTH_FAILED", "模型凭据无效或无权访问", retryable=False, status=response.status_code)
                    raise GatewayError("PROVIDER", f"PROVIDER_{response.status_code}", "模型服务异常", retryable=response.status_code >= 500, status=response.status_code)
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        item = json.loads(raw)
                    except ValueError as exc:
                        raise GatewayError("SCHEMA", "STREAM_INVALID_JSON", "模型流返回非法 JSON", retryable=False) from exc
                    choices = item.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0].get("delta") or {}).get("content")
                    if delta:
                        yield str(delta)
        except httpx.TimeoutException as exc:
            raise GatewayError("NETWORK", "TIMEOUT", "模型流调用超时", retryable=True) from exc
        except httpx.TransportError as exc:
            raise GatewayError("NETWORK", "TRANSPORT_ERROR", "模型流调用网络错误", retryable=True) from exc

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        request_id = _request_id()
        started = time.monotonic()
        data = self._post(_ENDPOINTS["embedding"], {"model": request.model, "input": request.input}, request_id=request_id)
        try:
            validated = OpenAIEmbeddingResponse.model_validate(data)
        except ValidationError as exc:
            raise GatewayError("SCHEMA", "EMBEDDING_SCHEMA_INVALID", "模型响应不符合向量协议", retryable=False) from exc
        if len(validated.data) != len(request.input):
            raise GatewayError("SCHEMA", "EMBEDDING_COUNT_MISMATCH", "向量数量与输入不一致", retryable=False)
        usage = validated.usage
        response = EmbeddingResponse(
            model=validated.model,
            data=[{"index": item.index, "embedding": item.embedding} for item in validated.data],
            usage=EmbeddingUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
            ),
            raw=data,
        )
        logger.debug(
            "gateway_embed",
            extra={
                "request_id": request_id,
                "model": request.model,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "batch_size": len(request.input),
            },
        )
        return response

    def rerank(self, request: RerankRequest) -> RerankResponse:
        request_id = _request_id()
        started = time.monotonic()
        payload = {"model": request.model, "query": request.query, "documents": request.documents}
        if request.top_n is not None:
            payload["top_n"] = request.top_n
        data = self._post(_ENDPOINTS["rerank"], payload, request_id=request_id)
        try:
            validated = OpenAIRerankResponse.model_validate(data)
        except ValidationError as exc:
            raise GatewayError("SCHEMA", "RERANK_SCHEMA_INVALID", "模型响应不符合重排协议", retryable=False) from exc
        response = RerankResponse(
            model=validated.model,
            results=[
                {"index": item.index, "relevance_score": item.relevance_score, "document": item.document}
                for item in validated.results
            ],
            raw=data,
        )
        logger.debug(
            "gateway_rerank",
            extra={
                "request_id": request_id,
                "model": request.model,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "documents": len(request.documents),
            },
        )
        return response
