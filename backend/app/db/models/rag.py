"""分类、切片数据模型（DD-19 §5.1-5.3）。

- classification_results：分类运行结果（版本级，每 input_hash 一条有效结果）；
- document_metadata：版本级文档元数据（分类产物 + 人工修正落点）；
- document_chunks：文档切片（后续 EMBED/INDEX 的输入）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CHAR, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from .mixins import TimestampMixin


class ClassificationResult(Base, TimestampMixin):
    """knowledge.classification_results —— 分类运行结果（DD-19 §5.1）。"""

    __tablename__ = "classification_results"
    __table_args__ = (
        Index(
            "uq_classification_results_version_hash", "version_id", "input_hash", unique=True
        ),
        Index("ix_classification_results_version_status", "version_id", "status"),
        Index("ix_classification_results_relevance_created", "relevance", "created_at"),
        {"schema": "knowledge", "comment": "分类结果"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.document_versions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="RUNNING", server_default="RUNNING"
    )
    relevance: Mapped[str | None] = mapped_column(String(32), nullable=True)
    relevance_confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    missing_fields: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)
    reason_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_builder_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    classification_config_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    input_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    token_usage_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentMetadata(Base):
    """knowledge.document_metadata —— 文档元数据（DD-19 §5.2）。"""

    __tablename__ = "document_metadata"
    __table_args__ = (
        Index("ix_document_metadata_product", "product_id"),
        Index("ix_document_metadata_doc_type", "document_type_id"),
        {"schema": "knowledge", "comment": "文档元数据"},
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.document_versions.id"), primary_key=True
    )
    classification_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.classification_results.id"), nullable=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.products.id"), nullable=True
    )
    product_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.product_versions.id"), nullable=True
    )
    document_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.document_types.id"), nullable=True
    )
    product_form_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.product_forms.id"), nullable=True
    )
    is_domestic: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    module_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)
    field_sources: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    field_confidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id"), nullable=True
    )


class DocumentChunk(Base, TimestampMixin):
    """knowledge.document_chunks —— 文档切片（DD-19 §5.3）。"""

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("uq_document_chunks_version_ordinal", "version_id", "ordinal", unique=True),
        Index("ix_document_chunks_version", "version_id"),
        Index("ix_document_chunks_content_sha", "content_sha256"),
        {"schema": "knowledge", "comment": "文档切片"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.document_versions.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    heading_path: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)
    locator_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
