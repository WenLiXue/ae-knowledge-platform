"""审计查询与响应 Schema（DD-17 §6.3）。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    """列表项。"""

    id: str
    occurred_at: datetime
    actor_type: str
    actor_name: str
    actor_account: str | None
    module: str
    action: str
    outcome: str
    error_code: str | None
    summary: str
    target_type: str | None
    target_id: str | None
    target_name: str | None
    source_ip: str | None
    request_id: str


class AuditLogDetailOut(AuditLogOut):
    """详情：追加变更、元数据与关联字段。不包含任何敏感值（已脱敏）。"""

    actor_user_id: str | None
    actor_key: str | None
    changes: list[dict]
    metadata: dict
    trace_id: str | None
    causation_id: str | None
    source_type: str
    user_agent: str | None
    prev_hash: str | None
    record_hash: str


class AuditListOut(BaseModel):
    items: list[AuditLogOut]
    next_cursor: str | None = None
    has_more: bool = False


class AuditSummaryOut(BaseModel):
    total: int
    by_module: list[dict]
    by_outcome: list[dict]


class AuditExportOut(BaseModel):
    id: str
    status: str
    row_count: int | None = None
    error_code: str | None = None
    filters: dict
    requested_at: datetime
    completed_at: datetime | None = None
    expires_at: datetime | None = None


class AuditExportCreate(BaseModel):
    """创建导出任务的筛选快照。约束与列表一致：默认最近 24 小时，最大 90 天。"""

    start_at: datetime | None = None
    end_at: datetime | None = None
    actor_user_id: UUID | None = None
    module: str | None = None
    action: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    outcome: str | None = None
    keyword: str | None = None


def audit_log_out(row) -> AuditLogOut:
    return AuditLogOut(
        id=str(row.id),
        occurred_at=row.occurred_at,
        actor_type=row.actor_type,
        actor_name=row.actor_name,
        actor_account=row.actor_account,
        module=row.module,
        action=row.action,
        outcome=row.outcome,
        error_code=row.error_code,
        summary=row.summary,
        target_type=row.target_type,
        target_id=row.target_id,
        target_name=row.target_name,
        source_ip=str(row.source_ip) if row.source_ip else None,
        request_id=row.request_id,
    )


def audit_log_detail_out(row) -> AuditLogDetailOut:
    base = audit_log_out(row)
    return AuditLogDetailOut(
        **base.model_dump(),
        actor_user_id=str(row.actor_user_id) if row.actor_user_id else None,
        actor_key=row.actor_key,
        changes=row.changes,
        metadata=row.metadata_,
        trace_id=row.trace_id,
        causation_id=str(row.causation_id) if row.causation_id else None,
        source_type=row.source_type,
        user_agent=row.user_agent,
        prev_hash=row.prev_hash,
        record_hash=row.record_hash,
    )


def audit_export_out(row) -> AuditExportOut:
    return AuditExportOut(
        id=str(row.id),
        status=row.status,
        row_count=row.row_count,
        error_code=row.error_code,
        filters=row.filters,
        requested_at=row.requested_at,
        completed_at=row.completed_at,
        expires_at=row.expires_at,
    )
