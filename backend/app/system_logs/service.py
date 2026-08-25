"""系统日志查询服务（读取 platform.log_events，只读）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models.log import LogEvent


@dataclass
class LogQuery:
    level: str | None = None
    service: str | None = None
    request_id: str | None = None
    task_id: str | None = None
    source_id: str | None = None
    version_id: str | None = None
    user_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    keyword: str | None = None


def list_logs(
    db: Session,
    q: LogQuery,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[LogEvent], int]:
    """按条件分页查询日志，返回 (items, total)，按时间倒序。"""
    stmt = select(LogEvent)
    if q.level:
        stmt = stmt.where(LogEvent.level == q.level.upper())
    if q.service:
        stmt = stmt.where(LogEvent.service == q.service)
    if q.request_id:
        stmt = stmt.where(LogEvent.request_id == q.request_id)
    if q.task_id:
        stmt = stmt.where(LogEvent.task_id == q.task_id)
    if q.source_id:
        stmt = stmt.where(LogEvent.source_id == q.source_id)
    if q.version_id:
        stmt = stmt.where(LogEvent.version_id == q.version_id)
    if q.user_id:
        try:
            uid = UUID(q.user_id)
        except ValueError:
            uid = None
        if uid is not None:
            stmt = stmt.where(LogEvent.user_id == uid)
    if q.since:
        stmt = stmt.where(LogEvent.created_at >= q.since)
    if q.until:
        stmt = stmt.where(LogEvent.created_at <= q.until)
    if q.keyword:
        stmt = stmt.where(LogEvent.message.ilike(f"%{q.keyword}%"))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(LogEvent.created_at.desc(), LogEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return list(rows), total
