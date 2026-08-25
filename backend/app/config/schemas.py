"""目录/知识库配置与 LLM 配置的 Pydantic Schema。"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


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
