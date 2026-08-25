"""分类器输出契约与输入结构（DD-19 §8.1、DD-05 §3.2-3.3）。

- ClassificationOutput：模型必须返回的唯一 JSON 结构，经程序校验后才被采纳；
- EvidenceBlock：输入构造器产出的受控文本块，携带稳定 locator_id；
- ClassificationInput：一次分类请求的完整输入描述（内部使用，含 taxonomy 快照）。
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class FieldEvidence(BaseModel):
    """字段级证据：引用输入块 locator 与原文摘录（DD-19 §8.1）。"""

    field: str
    locator_ids: list[str]
    excerpts: list[str] = Field(default_factory=list)


class ClassificationOutput(BaseModel):
    """分类候选输出。只声明候选值，不改任何业务状态（DD-05 §1）。"""

    relevance: Literal["RELEVANT", "IRRELEVANT", "UNCERTAIN"]
    relevance_confidence: float = Field(ge=0, le=1)
    product_code: str | None = None
    product_version_code: str | None = None
    document_type_code: str | None = None
    product_form_code: str | None = None
    is_domestic: bool | None = None
    module_name: str | None = None
    business_topic: str | None = None
    keywords: list[str] = Field(default_factory=list)
    summary: str | None = None
    field_confidence: dict[str, float] = Field(default_factory=dict)
    evidence: list[FieldEvidence] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    reason_summary: str = Field(min_length=1, max_length=1000)


class EvidenceBlock(BaseModel):
    """输入文本块：带稳定 locator_id、标题路径与块类型（DD-05 §3.2）。"""

    locator_id: str
    heading_path: list[str] = Field(default_factory=list)
    block_type: Literal["title", "heading", "paragraph", "list_item", "table_header", "table_row"]
    text: str


class ClassificationInput(BaseModel):
    """一次分类请求的输入描述（DD-05 §3.2 示意；taxonomy 为当前启用目录快照）。"""

    document_version_id: UUID
    source_type: str
    source_title: str
    filename: str | None = None
    content_sha256: str
    config_revision: int
    taxonomy: dict
    blocks: list[EvidenceBlock] = Field(default_factory=list)


class PendingConfirmRelevant(BaseModel):
    """确认相关（DD-19 §9）：可补充/修正分类元数据；未提供的字段沿用模型候选。"""

    expected_row_version: int = Field(ge=1)
    product_code: str | None = Field(default=None, max_length=128)
    product_version_code: str | None = Field(default=None, max_length=128)
    document_type_code: str | None = Field(default=None, max_length=128)
    product_form_code: str | None = Field(default=None, max_length=128)
    is_domestic: bool | None = None
    module_name: str | None = Field(default=None, max_length=256)
    business_topic: str | None = Field(default=None, max_length=256)
    summary: str | None = Field(default=None, max_length=2000)
    keywords: list[str] | None = Field(default=None, max_length=50)


class PendingConfirmIrrelevant(BaseModel):
    """确认无关（DD-19 §9）：来源下线并记录原因。"""

    expected_row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


class PendingReclassify(BaseModel):
    """重新分类（DD-19 §9）：可选指定分类配置 revision；缺省用当前 ACTIVE。"""

    config_revision: int | None = None
