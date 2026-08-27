"""处理任务管理 API（DD-03，登录用户可访问，只读）。

- GET /api/v1/admin/tasks：按 任务类型 / 状态 / 来源关键字 过滤，offset 分页；
  返回任务 ID、类型、状态、版本处理阶段、来源名、尝试次数、错误摘要与创建时间。
只读接口不做审计（审计覆盖可变操作）。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth.deps import get_current_admin
from ..db.models.knowledge import DocumentVersion, KnowledgeSource
from ..db.models.task import ProcessingTask
from ..db.models.user import User
from ..db.session import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["admin-tasks"])


@router.get("/tasks")
def admin_list_tasks(
    task_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None, description="来源名称或幂等键模糊匹配"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    stmt = select(ProcessingTask)
    if task_type:
        stmt = stmt.where(ProcessingTask.task_type == task_type)
    if status:
        stmt = stmt.where(ProcessingTask.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.outerjoin(KnowledgeSource, KnowledgeSource.id == ProcessingTask.source_id)
        stmt = stmt.where(
            or_(
                KnowledgeSource.display_name.ilike(like),
                ProcessingTask.idempotency_key.ilike(like),
            )
        )

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = list(
        db.execute(
            stmt.order_by(ProcessingTask.created_at.desc(), ProcessingTask.id.desc())
            .offset(offset)
            .limit(limit)
        ).scalars()
    )

    source_ids = {t.source_id for t in rows if t.source_id}
    version_ids = {t.version_id for t in rows if t.version_id}
    names: dict = {}
    if source_ids:
        names = dict(
            db.execute(
                select(KnowledgeSource.id, KnowledgeSource.display_name).where(
                    KnowledgeSource.id.in_(source_ids)
                )
            ).all()
        )
    stages: dict = {}
    if version_ids:
        stages = dict(
            db.execute(
                select(DocumentVersion.id, DocumentVersion.processing_stage).where(
                    DocumentVersion.id.in_(version_ids)
                )
            ).all()
        )

    items = [
        {
            "task_id": str(task.id),
            "task_type": task.task_type,
            "status": task.status,
            "stage": stages.get(task.version_id),
            "attempt_count": task.attempt_count,
            "max_attempts": task.max_attempts,
            "last_error_category": task.last_error_category,
            "last_error_code": task.last_error_code,
            "last_error_summary": task.last_error_summary,
            "source_id": str(task.source_id) if task.source_id else None,
            "source_name": names.get(task.source_id),
            "version_id": str(task.version_id) if task.version_id else None,
            "priority": task.priority,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        }
        for task in rows
    ]
    return {"data": {"items": items, "total": total, "limit": limit, "offset": offset}}
