import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import CHAR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from .mixins import RowVersionMixin, TimestampMixin


class KnowledgeSource(Base, TimestampMixin, RowVersionMixin):
    """knowledge.knowledge_sources —— 知识来源聚合根（DD-03 §5.1）。"""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        # 同一 canonical 键只允许一个非下线来源（并发提交的唯一防线）
        Index(
            "uq_active_source_key",
            "source_type",
            "canonical_key",
            unique=True,
            postgresql_where=text("status <> 'OFFLINE'"),
        ),
        Index("ix_knowledge_sources_owner_status", "owner_user_id", "status", "updated_at"),
        Index("ix_knowledge_sources_status_update", "status", "update_status"),
        {"schema": "knowledge", "comment": "知识来源"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PROCESSING", server_default="PROCESSING"
    )
    update_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="IDLE", server_default="IDLE"
    )
    # 与 document_versions 存在环形外键，使用 use_alter 延迟建立
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.document_versions.id", use_alter=True),
        nullable=True,
    )
    pending_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.document_versions.id", use_alter=True),
        nullable=True,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    offlined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)


class FeishuSourceDetail(Base):
    """knowledge.feishu_source_details —— 飞书来源定位信息（DD-03 §5.2）。"""

    __tablename__ = "feishu_source_details"
    __table_args__ = {"schema": "knowledge", "comment": "飞书来源详情"}

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.knowledge_sources.id"), primary_key=True
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_token: Mapped[str] = mapped_column(String(256), nullable=False)
    original_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    space_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    node_token: Mapped[str | None] = mapped_column(String(256), nullable=True)
    last_seen_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_seen_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DocumentVersion(Base, TimestampMixin, RowVersionMixin):
    """knowledge.document_versions —— 文档版本（DD-03 §5.4）。"""

    __tablename__ = "document_versions"
    __table_args__ = (
        Index("uq_document_versions_source_version", "source_id", "version_no", unique=True),
        Index("ix_document_versions_source_status", "source_id", "status"),
        {"schema": "knowledge", "comment": "文档版本"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.knowledge_sources.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    external_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="CREATED", server_default="CREATED"
    )
    processing_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    parser_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification_config_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    embedding_model_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    index_generation: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
