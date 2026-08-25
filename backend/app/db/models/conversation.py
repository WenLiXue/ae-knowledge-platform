"""检索运行与候选数据模型（DD-19 §5.4）。

- retrieval_runs：一次检索运行的记录（模式、降级 flag、配置 revision、阶段耗时、
  候选数量、证据状态）；正文不重复保存；
- retrieval_candidates：Top-K 候选明细（各阶段 rank/分数、是否进入最终证据及
  排除原因），(retrieval_run_id, chunk_id) 唯一。
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from .mixins import TimestampMixin


class RetrievalRun(Base, TimestampMixin):
    """conversation.retrieval_runs —— 一次检索运行记录（DD-19 §5.4）。"""

    __tablename__ = "retrieval_runs"
    __table_args__ = (
        Index("ix_retrieval_runs_created", "created_at"),
        {"schema": "conversation", "comment": "检索运行记录"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_question: Mapped[str] = mapped_column(Text, nullable=False)
    query_texts: Mapped[list | None] = mapped_column(JSONB, nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.products.id"), nullable=True
    )
    version_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    document_type_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # HYBRID / BM25_ONLY / FAILED（双召回失败记录 FAILED 不生成答案）
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    degradation_flags: Mapped[list | None] = mapped_column(ARRAY(String), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="SUCCEEDED", server_default="SUCCEEDED"
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    config_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    embedding_model_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rerank_model_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    params_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    stage_duration_ms: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    candidate_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # SUFFICIENT / PARTIAL / INSUFFICIENT（确定性信号，供 Phase 6 证据充分度判断）
    evidence_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RetrievalCandidate(Base, TimestampMixin):
    """conversation.retrieval_candidates —— 检索候选明细（DD-19 §5.4）。"""

    __tablename__ = "retrieval_candidates"
    __table_args__ = (
        Index("uq_retrieval_candidates_run_chunk", "retrieval_run_id", "chunk_id", unique=True),
        Index("ix_retrieval_candidates_run", "retrieval_run_id"),
        {"schema": "conversation", "comment": "检索候选"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    retrieval_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.retrieval_runs.id"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.document_chunks.id"), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.knowledge_sources.id"), nullable=True
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.document_versions.id"), nullable=True
    )
    ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    bm25_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vector_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bm25_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    vector_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rrf_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rerank_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_evidence: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    evidence_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exclusion_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    score_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    title_snapshot: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
