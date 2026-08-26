"""LLM 模型管理与服务配置的 Pydantic Schema（DD-20 §9）。

- 模型表单只包含管理员完成配置所需的字段；温度/Top P/最大 Token/超时/重试等
  技术参数由系统维护默认值，不在 V1 表单暴露（MC-05）。
- API Key 的编辑语义：缺失或 null 保持当前密钥，非空字符串替换，空字符串视为保持。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ModelType = Literal["CHAT", "EMBEDDING", "RERANK"]
# V1 服务商为受控标签（DD-20 §6.2“至少支持 openai-compatible”）：
# 协议行为统一走 openai-compatible 适配器，服务商名称仅作管理员识别用途，
# 不硬编码客户特定枚举值。运行时适配器选择由后续 DD-19 按 provider 映射。
Provider = str
Protocol = Literal["openai-compatible", "anthropic"]
ServiceType = Literal["QA", "DOCUMENT_CLASSIFICATION", "DOCUMENT_EMBEDDING", "RETRIEVAL_RERANK"]


# ---- 模型管理 ----

class LlmModelCreate(BaseModel):
    """新增模型配置。"""

    name: str = Field(min_length=1, max_length=128)
    model_type: ModelType
    provider: Provider = Field(default="openai-compatible", min_length=1, max_length=64)
    protocol: Protocol = "openai-compatible"
    base_url: str = Field(min_length=1, max_length=512)
    model_name: str = Field(min_length=1, max_length=128)
    embedding_dimension: int | None = Field(default=None, ge=1, le=32768)
    normalize_embeddings: bool | None = None
    api_key: str | None = None
    enabled: bool = True
    expected_revision: int | None = None


class LlmModelUpdate(BaseModel):
    """编辑模型配置。字段缺失表示不修改；api_key 为 null 表示保持当前密钥。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    model_type: ModelType | None = None
    provider: Provider | None = Field(default=None, min_length=1, max_length=64)
    protocol: Protocol | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=512)
    model_name: str | None = Field(default=None, min_length=1, max_length=128)
    embedding_dimension: int | None = Field(default=None, ge=1, le=32768)
    normalize_embeddings: bool | None = None
    api_key: str | None = None
    enabled: bool | None = None
    expected_revision: int | None = None


class LlmModelOut(BaseModel):
    """模型配置输出。密钥永不返回（只返回是否已配置，MC-09）。"""

    id: str
    name: str
    model_type: ModelType
    provider: str
    protocol: Protocol
    base_url: str
    model_name: str
    embedding_dimension: int | None
    normalize_embeddings: bool | None
    enabled: bool
    has_api_key: bool
    used_by: list[str]


class LlmModelsOut(BaseModel):
    revision: int | None
    items: list[LlmModelOut]


# ---- 连接测试 ----

class LlmModelTestRequest(BaseModel):
    """测试尚未保存或正在编辑的模型配置（DD-20 §9.3）。

    两种密钥来源：
    - api_key 非空：测试该值但不保存；
    - api_key 为 null 且携带 model_id：使用已保存密钥。
    """

    model_type: ModelType
    provider: Provider = Field(default="openai-compatible", min_length=1, max_length=64)
    protocol: Protocol = "openai-compatible"
    base_url: str = Field(min_length=1, max_length=512)
    model_name: str = Field(min_length=1, max_length=128)
    embedding_dimension: int | None = Field(default=None, ge=1, le=32768)
    normalize_embeddings: bool | None = None
    api_key: str | None = None
    model_id: str | None = None


class LlmModelTestResult(BaseModel):
    ok: bool
    message: str
    duration_ms: float
    dimension: int | None = None


# ---- 服务配置 ----

class ServiceBindingModel(BaseModel):
    id: str
    name: str
    model_name: str


class ServiceBindingOut(BaseModel):
    service_type: ServiceType
    display_name: str
    description: str
    required: bool
    model: ServiceBindingModel | None


class ServiceBindingsOut(BaseModel):
    revision: int | None
    services: list[ServiceBindingOut]
    models: list[LlmModelOut]


class ServiceBindingsUpdate(BaseModel):
    """原子保存全部服务绑定（DD-20 §9.2）。任一绑定不合法时不保存任何一项。"""

    expected_revision: int
    bindings: dict[ServiceType, str | None]
