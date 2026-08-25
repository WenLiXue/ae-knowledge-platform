"""目录/知识库配置与 LLM 配置的 Pydantic Schema。"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator


# ---- 目录查询（public） ----

class CatalogItem(BaseModel):
    id: str
    code: str
    name: str
    status: str
    sort_order: int


class ProductOut(CatalogItem):
    pass


class ProductVersionOut(BaseModel):
    id: str
    product_id: str
    version_code: str
    major_version: int | None = None
    minor_version: int | None = None
    release_date: date | None = None
    status: str
    sort_order: int


class DocumentTypeOut(CatalogItem):
    description: str | None = None


class ProductFormOut(CatalogItem):
    pass


class SourcePriorityOut(BaseModel):
    source_code: str
    display_name: str
    priority: int
    status: str


# ---- 管理员 Catalog CRUD ----

class ProductCreate(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    status: str = "ENABLED"
    sort_order: int = 0


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    status: str | None = None
    sort_order: int | None = None
    row_version: int | None = None


class ProductVersionCreate(BaseModel):
    version_code: str = Field(min_length=1, max_length=128)
    major_version: int | None = None
    minor_version: int | None = None
    release_date: date | None = None
    sort_order: int = 0


class ProductVersionUpdate(BaseModel):
    version_code: str | None = Field(default=None, min_length=1, max_length=128)
    major_version: int | None = None
    minor_version: int | None = None
    release_date: date | None = None
    status: str | None = None
    sort_order: int | None = None
    row_version: int | None = None


class DocumentTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    description: str | None = None
    status: str = "ENABLED"
    sort_order: int = 0


class DocumentTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    status: str | None = None
    sort_order: int | None = None
    row_version: int | None = None


class ProductFormCreate(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    status: str = "ENABLED"
    sort_order: int = 0


class ProductFormUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    status: str | None = None
    sort_order: int | None = None
    row_version: int | None = None


# ---- 来源优先级 ----

class SourcePriorityPatch(BaseModel):
    source_code: str
    priority: int = Field(ge=1, le=9999)


class SourcePrioritiesUpdate(BaseModel):
    items: list[SourcePriorityPatch] = Field(min_length=1, max_length=50)


# ---- LLM 配置 ----

class LLMConfig(BaseModel):
    provider: str = Field(default="openai-compatible", max_length=64)
    base_url: str = Field(default="", max_length=512)
    model: str = Field(default="", max_length=128)
    temperature: float = Field(default=0.2, ge=0, le=2)
    top_p: float = Field(default=1.0, ge=0, le=1)
    max_tokens: int = Field(default=2048, ge=1, le=1_000_000)
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    classification_model: str = Field(default="", max_length=128)
    embedding_model: str = Field(default="", max_length=128)
    enabled: bool = False

    @field_validator("base_url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("base_url 必须以 http:// 或 https:// 开头")
        return value


class LLMConfigOut(LLMConfig):
    has_api_key: bool = False


class LLMConfigUpdate(LLMConfig):
    # api_key：提供则更新；空字符串表示清除；None 表示保持不变
    api_key: str | None = None


class LLMTestResult(BaseModel):
    ok: bool
    message: str
