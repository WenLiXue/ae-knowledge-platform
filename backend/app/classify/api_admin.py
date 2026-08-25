"""人工确认 API（DD-19 §9，仅管理员）。

审计约定（DD-17 §6.1）：服务层只 flush()，成功后在本层追加 SUCCESS 审计并统一
commit（业务 + 审计原子提交）；业务校验失败回滚并用独立短事务写 FAILURE。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..audit import service as audit_service
from ..audit.context import build_context
from ..audit.deps import require_admin_action
from ..auth.deps import get_current_admin
from ..db.models.user import User
from ..db.session import get_db
from . import confirmation
from .schemas import PendingConfirmIrrelevant, PendingConfirmRelevant, PendingReclassify

router = APIRouter(prefix="/api/v1/admin/classification-pending", tags=["admin-classification"])


def _handle(exc: confirmation.ConfirmationError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


def _audit_success(
    db: Session,
    admin: User,
    request: Request,
    action: str,
    *,
    target_id: str,
    target_name: str,
    changes: list[dict] | None = None,
) -> None:
    audit_service.record_success(
        db,
        audit_service.success_event(
            user=admin,
            context=build_context(request),
            action=action,
            summary=action,
            target_type="CLASSIFICATION_PENDING",
            target_id=target_id,
            target_name=target_name,
            changes=changes,
        ),
    )


def _audit_failure(
    admin: User,
    request: Request,
    action: str,
    *,
    error_code: str,
    target_id: str | None = None,
    target_name: str | None = None,
) -> None:
    audit_service.record_failure_independent(
        audit_service.failure_event(
            user=admin,
            context=build_context(request),
            action=action,
            summary=action,
            error_code=error_code,
            target_type="CLASSIFICATION_PENDING",
            target_id=target_id,
            target_name=target_name,
        )
    )


@router.get("")
def admin_list_pending(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    return {"data": {"items": confirmation.list_pending(db)}}


@router.get("/{version_id}")
def admin_get_pending(
    version_id: UUID, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)
):
    item = confirmation.get_pending_detail(db, version_id)
    if item is None:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_PENDING", "message": "版本不在待确认列表"}
        )
    return {"data": item}


@router.post("/{version_id}/confirm-relevant")
def admin_confirm_relevant(
    version_id: UUID,
    data: PendingConfirmRelevant,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("classification.pending.confirm_relevant")),
):
    try:
        item = confirmation.confirm_relevant(db, version_id, data, user_id=admin.id)
    except confirmation.ConfirmationError as exc:
        _audit_failure(
            admin, request, "classification.pending.confirm_relevant",
            error_code=exc.code, target_id=str(version_id),
        )
        raise _handle(exc)
    _audit_success(
        db, admin, request, "classification.pending.confirm_relevant",
        target_id=str(version_id), target_name=item["source_name"],
        changes=audit_service.build_changes({"relevance": ("UNCERTAIN", "RELEVANT")}),
    )
    db.commit()
    return {"data": item}


@router.post("/{version_id}/confirm-irrelevant")
def admin_confirm_irrelevant(
    version_id: UUID,
    data: PendingConfirmIrrelevant,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("classification.pending.confirm_irrelevant")),
):
    try:
        item = confirmation.confirm_irrelevant(db, version_id, data, user_id=admin.id)
    except confirmation.ConfirmationError as exc:
        _audit_failure(
            admin, request, "classification.pending.confirm_irrelevant",
            error_code=exc.code, target_id=str(version_id),
        )
        raise _handle(exc)
    _audit_success(
        db, admin, request, "classification.pending.confirm_irrelevant",
        target_id=str(version_id), target_name=item["source_name"],
        changes=audit_service.build_changes({"relevance": ("UNCERTAIN", "IRRELEVANT")}),
    )
    db.commit()
    return {"data": item}


@router.post("/{version_id}/reclassify")
def admin_reclassify(
    version_id: UUID,
    data: PendingReclassify,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("classification.pending.reclassify")),
):
    try:
        item = confirmation.schedule_reclassify(db, version_id, data, user_id=admin.id)
    except confirmation.ConfirmationError as exc:
        _audit_failure(
            admin, request, "classification.pending.reclassify",
            error_code=exc.code, target_id=str(version_id),
        )
        raise _handle(exc)
    _audit_success(
        db, admin, request, "classification.pending.reclassify",
        target_id=str(version_id), target_name=item["source_name"],
        changes=audit_service.build_changes({"relevance": ("UNCERTAIN", "RECLASSIFY")}),
    )
    db.commit()
    return {"data": item}
