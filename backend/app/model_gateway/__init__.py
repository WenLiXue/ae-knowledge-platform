"""Model Gateway：供应商无关的模型调用适配层（DD-19 §7）。"""

from .base import (
    ChatRequest,
    ChatResponse,
    GatewayTool,
    GatewayToolCall,
    EmbeddingRequest,
    EmbeddingResponse,
    RerankRequest,
    RerankResponse,
)
from .errors import GatewayError
from .factory import create_gateway
from .openai_compatible import OpenAICompatibleGateway

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "GatewayTool",
    "GatewayToolCall",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "GatewayError",
    "OpenAICompatibleGateway",
    "RerankRequest",
    "RerankResponse",
    "create_gateway",
]
