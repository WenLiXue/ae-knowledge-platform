"""检索领域契约（DD-19 §12.1、DD-07 §4.1/§9.1）。

- RetrievalFilters：本次查询的显式过滤条件（ID 必须来自数据库目录，禁止任意输入）；
- QueryPlan：一次检索的完整查询计划（操作类型、归一化问题、多路 query_text、过滤）；
- EvidenceItem：进入最终证据的可解释证据（chunk/版本/标题/章节/locator/score_details）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RetrievalFilters(BaseModel):
    """查询显式条件。所有 ID 必须来自数据库目录或会话已验证条件。"""

    product_id: uuid.UUID | None = None
    version_ids: list[uuid.UUID] = Field(default_factory=list)
    document_type_ids: list[uuid.UUID] = Field(default_factory=list)


class QueryPlan(BaseModel):
    """DD-19 §12.1 查询计划。operation 在 Phase 5 无查询理解模型时默认 ANSWER，
    Phase 6 查询理解将填充 normalized_question/query_texts/operation。"""

    operation: Literal["ANSWER", "SUMMARIZE", "RELATE", "EXPLAIN", "CLARIFY"] = "ANSWER"
    normalized_question: str
    query_texts: list[str]
    product_id: uuid.UUID | None = None
    version_ids: list[uuid.UUID] = Field(default_factory=list)
    document_type_ids: list[uuid.UUID] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None


class EvidenceItem(BaseModel):
    """DD-07 §9.1 证据对象。evidence_id 是本次检索内部稳定引用键（E1..En）。"""

    evidence_id: str
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    document_version_id: uuid.UUID
    content: str
    title: str
    heading_path: list[str] = Field(default_factory=list)
    locator: dict = Field(default_factory=dict)
    source_priority: int = 0
    source_updated_at: datetime | None = None
    score_details: dict = Field(default_factory=dict)
