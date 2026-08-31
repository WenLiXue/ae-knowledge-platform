"""审计管理 API（DD-17 §6.3，仅管理员可访问）。

- GET  /api/v1/admin/audit-logs：游标分页列表与组合筛选；
- GET  /api/v1/admin/audit-logs/summary：时间窗口内模块/结果计数；
- GET  /api/v1/admin/audit-logs/{event_id}：详情（读取本身按策略审计）；
- POST /api/v1/admin/audit-exports：创建异步导出任务，返回 202；
- GET  /api/v1/admin/audit-exports/{export_id}：导出状态；
- GET  /api/v1/admin/audit-exports/{export_id}/download：短时认证下载。

列表参数默认最近 24 小时、单次最大 90 天；limit 默认 50、最大 200。
关键词只匹配日志编号、操作者快照和对象快照，不扫描 JSON 正文。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..db.models.user import User
from ..db.session import get_db
from . import service
from .context import build_context
from .deps import require_admin_action
from .schemas import (
    AuditExportCreate,
    AuditExportOut,
    AuditListOut,
    AuditLogDetailOut,
    AuditLogOut,
    AuditSummaryOut,
    audit_export_out,
    audit_log_detail_out,
    audit_log_out,
)
from .service import AuditError

router = APIRouter(prefix="/api/v1/admin", tags=["admin-audit"])

_VALID_OUTCOMES = {"SUCCESS", "FAILURE", "DENIED"}


def _handle(exc: AuditError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


def _resolve_time_range(start_at: datetime | None, end_at: datetime | None) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if start_at is None and end_at is None:
        return now - timedelta(hours=24), now
    if start_at is None:
        start_at = end_at - timedelta(hours=24)
    if end_at is None:
        end_at = start_at + timedelta(hours=24)
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=timezone.utc)
    if start_at > end_at:
        raise AuditError("INVALID_TIME_RANGE", "开始时间不能晚于结束时间", status=400)
    if (end_at - start_at) > timedelta(days=service.MAX_QUERY_DAYS):
        raise AuditError("TIME_RANGE_TOO_LARGE", f"时间范围不能超过 {service.MAX_QUERY_DAYS} 天", status=400)
    return start_at, end_at


@router.get("/audit-logs")
def list_audit_logs(
    request: Request,
    start_at: datetime | None = Query(None),
    end_at: datetime | None = Query(None),
    actor_user_id: UUID | None = Query(None),
    module: str | None = Query(None),
    action: str | None = Query(None),
    target_type: str | None = Query(None),
    target_id: str | None = Query(None),
    outcome: str | None = Query(None),
    keyword: str | None = Query(None),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("audit.query")),
) -> dict[str, object]:
    del request, admin  # 仅鉴权
    if outcome is not None and outcome not in _VALID_OUTCOMES:
        raise HTTPException(400, detail={"code": "INVALID_OUTCOME", "message": "结果只支持 SUCCESS/FAILURE/DENIED"})
    try:
        start, end = _resolve_time_range(start_at, end_at)
        rows, next_cursor, has_more = service.query_audit_logs(
            db,
            start_at=start,
            end_at=end,
            actor_user_id=str(actor_user_id) if actor_user_id else None,
            module=module,
            action=action,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            keyword=keyword,
            cursor=cursor,
            limit=limit,
        )
    except AuditError as exc:
        raise _handle(exc)
    return {
        "data": AuditListOut(
            items=[audit_log_out(r) for r in rows],
            next_cursor=next_cursor,
            has_more=has_more,
        )
    }


@router.get("/audit-logs/summary")
def audit_log_summary(
    request: Request,
    start_at: datetime | None = Query(None),
    end_at: datetime | None = Query(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("audit.query")),
) -> dict[str, object]:
    del request, admin
    try:
        start, end = _resolve_time_range(start_at, end_at)
        data = service.get_summary(db, start_at=start, end_at=end)
    except AuditError as exc:
        raise _handle(exc)
    return {"data": AuditSummaryOut(**data)}


@router.get("/audit-logs/{event_id}")
def get_audit_log_detail(
    event_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("audit.view_detail")),
) -> dict[str, object]:
    row = db.get(service.AuditLog, event_id)
    if row is None:
        raise HTTPException(404, detail={"code": "AUDIT_NOT_FOUND", "message": "审计记录不存在"})
    ctx = build_context(request)
    service.record_success(
        db,
        service.success_event(
            user=admin,
            context=ctx,
            action="audit.view_detail",
            summary=f"查看审计详情 {event_id}",
            target_type="AUDIT_LOG",
            target_id=str(event_id),
            target_name=row.actor_name,
        ),
    )
    db.commit()
    return {"data": audit_log_detail_out(row)}


@router.post("/audit-exports", status_code=202)
def create_audit_export(
    data: AuditExportCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("audit.export")),
) -> dict[str, object]:
    try:
        start, end = _resolve_time_range(data.start_at, data.end_at)
        if data.outcome is not None and data.outcome not in _VALID_OUTCOMES:
            raise AuditError("INVALID_OUTCOME", "结果只支持 SUCCESS/FAILURE/DENIED", status=400)
        filters = {
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "actor_user_id": str(data.actor_user_id) if data.actor_user_id else None,
            "module": data.module,
            "action": data.action,
            "target_type": data.target_type,
            "target_id": data.target_id,
            "outcome": data.outcome,
            "keyword": data.keyword,
        }
        row = service.create_export(db, admin, filters, build_context(request))
    except AuditError as exc:
        raise _handle(exc)
    ctx = build_context(request)
    service.record_success(
        db,
        service.success_event(
            user=admin,
            context=ctx,
            action="audit.export",
            summary="创建审计日志导出任务",
            target_type="AUDIT_EXPORT",
            target_id=str(row.id),
        ),
    )
    db.commit()
    return {"data": audit_export_out(row)}


@router.get("/audit-exports/{export_id}")
def get_audit_export_status(
    export_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("audit.export")),
) -> dict[str, object]:
    del request, admin
    row = service.get_export(db, str(export_id))
    return {"data": audit_export_out(row)}


@router.get("/audit-exports/{export_id}/download")
def download_audit_export(
    export_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("audit.export")),
):
    try:
        row, path = service.download_export(db, str(export_id))
    except AuditError as exc:
        raise _handle(exc)
    ctx = build_context(request)
    service.record_success(
        db,
        service.success_event(
            user=admin,
            context=ctx,
            action="audit.export",
            summary=f"下载审计导出（{row.row_count} 条）",
            target_type="AUDIT_EXPORT",
            target_id=str(row.id),
            metadata={"export_id": str(row.id), "rows": row.row_count},
        ),
    )
    db.commit()
    return FileResponse(
        path,
        filename=f"audit_logs_{row.id}.csv",
        media_type="text/csv; charset=utf-8",
    )
