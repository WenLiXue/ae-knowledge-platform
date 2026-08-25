"""Model Gateway 工厂（DD-19 §7）。

按活动配置（app/llm 解析出的 ResolvedModel）创建适配器。
业务（分类/问答/Embedding/Rerank）只持有 gateway 实例，不自行拼供应商 URL。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from .errors import GatewayError
from .openai_compatible import OpenAICompatibleGateway

if TYPE_CHECKING:
    from app.llm.runtime import ResolvedModel


def create_gateway(
    model: "ResolvedModel",
    *,
    http_client: httpx.Client | None = None,
    total_timeout: float = 300.0,
    retries: int = 2,
    retry_backoff_seconds: float = 0.5,
) -> OpenAICompatibleGateway:
    """按 provider 创建 gateway。当前仅支持 openai-compatible。"""
    if model.provider != "openai-compatible":
        raise GatewayError(
            "CONFIG",
            "UNSUPPORTED_PROVIDER",
            f"不支持的模型供应商: {model.provider}",
            retryable=False,
        )
    if not model.api_key:
        raise GatewayError(
            "CONFIG",
            "MODEL_API_KEY_MISSING",
            "模型未配置 API Key",
            retryable=False,
        )
    return OpenAICompatibleGateway(
        base_url=model.base_url,
        api_key=model.api_key,
        model=model.model_name,
        total_timeout=total_timeout,
        retries=retries,
        retry_backoff_seconds=retry_backoff_seconds,
        http_client=http_client,
    )
