"""会话与问答 API Schema（DD-08 §10-14、DD-10）。

- QueryFilters：查询条件快照（产品/版本/文档类型，ID 来自数据库目录）；
- Conversation/Message/Answer/Citation/Feedback：会话与问答契约；
- AnswerBlock：结构化回答块（paragraph/table/list 等，引用编号）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class QueryFilters(BaseModel):
    product_id: uuid.UUID | None = None
    product_version_id: uuid.UUID | None = None
    document_type_id: uuid.UUID | None = None


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    filters: QueryFilters | None = None


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    filters: QueryFilters | None = None


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    filters: dict
    last_message_at: datetime | None
    created_at: datetime


class MessageCreate(BaseModel):
    content: str
    # 省略=使用会话当前条件；出现=完整替换（三个可空字段都要出现，显式 null 清空）
    filters: QueryFilters | None = None


class CreateMessageResult(BaseModel):
    message_id: uuid.UUID
    answer_id: uuid.UUID
    status: str
    events_url: str


class AnswerBlock(BaseModel):
    block_id: str
    type: Literal["paragraph", "table", "list", "scope", "warning", "conflict"]
    content: dict | str
    citation_nos: list[int] = Field(default_factory=list)


class CitationLocationOut(BaseModel):
    """同一文档来源下的一个精确证据片段。"""

    chunk_id: uuid.UUID | None = None
    heading_path: list[str] = Field(default_factory=list)
    locator: dict = Field(default_factory=dict)
    excerpt: str | None = None


class AnswerCitationOut(BaseModel):
    citation_no: int
    source_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None
    document_title: str
    document_type: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    version_label: str | None = None
    source_updated_at: datetime | None = None
    excerpt: str | None = None
    original_url: str | None = None
    availability: str = "AVAILABLE"
    support_count: int = 1
    locations: list[CitationLocationOut] = Field(default_factory=list)


class AnswerOut(BaseModel):
    id: uuid.UUID
    status: str
    progress_stage: str | None = None
    answer_type: str | None = None
    summary: str | None = None
    blocks: list[AnswerBlock] = Field(default_factory=list)
    citations: list[AnswerCitationOut] = Field(default_factory=list)
    degradation_flags: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_summary: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class MessageOut(BaseModel):
    id: str
    conversation_id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    answer: AnswerOut | None = None
    created_at: datetime


class FeedbackIn(BaseModel):
    rating: Literal["HELPFUL", "NOT_HELPFUL"]
    reason_codes: list[str] = Field(default_factory=list)
    comment: str | None = Field(default=None, max_length=1000)


class CitationDetailOut(BaseModel):
    citation_no: int
    supported_claim: str | None = None
    source_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None
    document_title: str
    document_type: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    locator: dict = Field(default_factory=dict)
    excerpt: str | None = None
    original_url: str | None = None
    availability: str = "AVAILABLE"
    support_count: int = 1
    locations: list[CitationLocationOut] = Field(default_factory=list)
