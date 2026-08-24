import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from .mixins import RowVersionMixin, TimestampMixin


class ProcessingTask(Base, TimestampMixin, RowVersionMixin):
    """tasking.processing_tasks —— 处理任务（DD-03 §6.1）。"""

    __tablename__ = "processing_tasks"
    __table_args__ = (
        # 同一业务幂等键只允许一个未终结任务
        Index(
            "uq_open_task_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'RUNNING', 'RETRY_WAIT')"),
        ),
        # Worker 领取顺序
        Index(
            "ix_task_claim",
            "priority",
            "scheduled_at",
            "created_at",
            postgresql_where=text("status IN ('PENDING', 'RETRY_WAIT')"),
        ),
        Index("ix_tasks_source", "source_id"),
        Index("ix_tasks_version", "version_id"),
        {"schema": "tasking", "comment": "处理任务"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.knowledge_sources.id"), nullable=True
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.document_versions.id"), nullable=True
    )
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasking.processing_tasks.id"), nullable=True
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("100"))
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id"), nullable=True
    )


class TaskAttempt(Base):
    """tasking.task_attempts —— 每次实际执行的记录（DD-03 §6.2）。"""

    __tablename__ = "task_attempts"
    __table_args__ = (
        Index("uq_task_attempts_task_no", "task_id", "attempt_no", unique=True),
        {"schema": "tasking", "comment": "任务执行尝试"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasking.processing_tasks.id"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
