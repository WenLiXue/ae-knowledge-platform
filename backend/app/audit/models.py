"""审计领域模型（platform schema，DD-17 §5）。

- AuditLog：只追加的审计事件。record_hash 为规范序列化后的 HMAC-SHA256，
  prev_hash 指向同链上一条记录的摘要，构成哈希链用于事后发现篡改。
- AuditExport：异步导出任务的状态表（文件路径与行数只在状态里记录，下载接口按 ID 短时认证）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CHAR, DateTime, ForeignKey, Index, Integer, SmallInteger, String, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class AuditLog(Base):
    """platform.audit_logs —— 操作审计日志。"""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_occurred_id", text("occurred_at DESC"), text("id DESC")),
        Index("ix_audit_logs_actor_occurred", "actor_user_id", text("occurred_at DESC")),
        Index("ix_audit_logs_module_outcome_occurred", "module", "outcome", text("occurred_at DESC")),
        Index("ix_audit_logs_action_occurred", "action", text("occurred_at DESC")),
        Index("ix_audit_logs_target_occurred", "target_type", "target_id", text("occurred_at DESC")),
        Index("ix_audit_logs_request_id", "request_id"),
        {"schema": "platform", "comment": "操作审计日志"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)  # USER/SYSTEM/WORKER/SERVICE
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True
    )
    actor_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_account: Mapped[str | None] = mapped_column(String(320), nullable=True)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)  # SUCCESS/FAILURE/DENIED
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    changes: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # metadata 为 SQLAlchemy Declarative 保留名，属性改 metadata_，列名保持 metadata（DD-17 §5.1）
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)  # WEB/API/WORKER/SCHEDULER
    source_ip: Mapped[object | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    record_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default=text("1")
    )


class AuditExport(Base):
    """platform.audit_exports —— 审计导出任务。"""

    __tablename__ = "audit_exports"
    __table_args__ = (
        Index("ix_audit_exports_requested_at", "requested_at"),
        {"schema": "platform", "comment": "审计导出任务"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default="PENDING"
    )  # PENDING/RUNNING/READY/FAILED/EXPIRED
    filters: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
