"""运行日志表（platform schema）。ERROR 级记录由 DbLogHandler best-effort 写入。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class LogEvent(Base):
    """platform.log_events —— 结构化运行日志（ERROR 级持久化，append-only）。"""

    __tablename__ = "log_events"
    __table_args__ = (
        Index("ix_log_events_created", "created_at"),
        Index("ix_log_events_service_created", "service", "created_at"),
        Index("ix_log_events_level_created", "level", "created_at"),
        Index("ix_log_events_request_id", "request_id"),
        Index("ix_log_events_task_id", "task_id"),
        {"schema": "platform", "comment": "运行日志（ERROR 级持久化）"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    service: Mapped[str] = mapped_column(String(16), nullable=False, default="api", server_default="api")
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    logger: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message: Mapped[str] = mapped_column(String(1024), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True
    )
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 关联 ID 不加 FK：日志 append-only，来源/版本/任务可能先于日志被清理
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    detail: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
