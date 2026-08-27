"""系统日志查询 API（登录用户可访问）。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth.deps import get_current_admin
from ..db.models.log import LogEvent
from ..db.models.user import User
from ..db.session import get_db
from . import service as log_service

router = APIRouter(prefix="/api/v1/admin", tags=["admin-logs"])


def _log_dict(row: LogEvent) -> dict:
    return {
        "id": str(row.id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "service": row.service,
        "level": row.level,
        "logger": row.logger,
        "message": row.message,
        "error_code": row.error_code,
        "request_id": row.request_id,
        "user_id": str(row.user_id) if row.user_id else None,
        "ip": row.ip,
        "task_id": row.task_id,
        "source_id": row.source_id,
        "version_id": row.version_id,
        "detail": row.detail,
        "traceback": row.traceback,
    }


@router.get("/system-logs")
def admin_system_logs(
    level: str | None = None,
    service: str | None = Query(None, pattern="^(api|worker)$"),
    request_id: str | None = None,
    task_id: str | None = None,
    source_id: str | None = None,
    version_id: str | None = None,
    user_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    keyword: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """分页查询运行日志（ERROR+ 落库记录）。"""
    q = log_service.LogQuery(
        level=level,
        service=service,
        request_id=request_id,
        task_id=task_id,
        source_id=source_id,
        version_id=version_id,
        user_id=user_id,
        since=since,
        until=until,
        keyword=keyword,
    )
    items, total = log_service.list_logs(db, q, limit=limit, offset=offset)
    return {"data": {"items": [_log_dict(row) for row in items], "total": total}}
