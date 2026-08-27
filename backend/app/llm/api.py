"""LLM 模型管理与服务配置 API（登录用户可访问，DD-20 §9）。

每个已纳入审计范围的变更操作：
- 服务层只 flush()，成功后在本层追加 SUCCESS 审计并统一 commit（业务+审计原子提交）；
- 业务校验失败时回滚业务事务，用独立短事务写 FAILURE，再返回原始错误；
- 权限失败由 require_admin_action 依赖写 DENIED。
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
from . import service
from .schemas import (
    LlmModelCreate,
    LlmModelsOut,
    LlmModelOut,
    LlmModelTestRequest,
    LlmModelTestResult,
    LlmModelUpdate,
    ServiceBindingsOut,
    ServiceBindingsUpdate,
)

router = APIRouter(prefix="/api/v1/admin/llm-config", tags=["admin-llm-config"])


def _handle(exc: service.LLMConfigError) -> HTTPException:
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
            target_type="LLM_MODEL",
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
            target_type="LLM_MODEL",
            target_id=target_id,
            target_name=target_name,
        )
    )


# ---- 模型管理 ----

@router.get("/models")
def admin_list_models(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    return {"data": LlmModelsOut(**service.list_models(db)).model_dump()}


@router.post("/models", status_code=201)
def admin_create_model(
    data: LlmModelCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.llm.model.create")),
):
    try:
        model = service.create_model(db, data, admin.id)
    except service.LLMConfigError as exc:
        _audit_failure(admin, request, "config.llm.model.create", error_code=exc.code, target_name=data.name)
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.llm.model.create", target_id=model["id"], target_name=model["name"],
        changes=audit_service.build_changes({
            "name": (None, model["name"]), "model_type": (None, model["model_type"]),
            "provider": (None, model["provider"]), "base_url": (None, model["base_url"]),
            "model_name": (None, model["model_name"]), "enabled": (None, model["enabled"]),
            "has_api_key": (None, model["has_api_key"]),
        }),
    )
    db.commit()
    return {"data": LlmModelOut(**model).model_dump()}


@router.patch("/models/{model_id}")
def admin_update_model(
    model_id: UUID,
    data: LlmModelUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.llm.model.update")),
):
    before = _model_by_id(db, str(model_id))
    try:
        model = service.update_model(db, str(model_id), data, admin.id)
    except service.LLMConfigError as exc:
        _audit_failure(
            admin, request, "config.llm.model.update", error_code=exc.code,
            target_id=str(model_id), target_name=before.get("name") if before else None,
        )
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.llm.model.update", target_id=model["id"], target_name=model["name"],
        changes=_model_changes(before, model),
    )
    db.commit()
    return {"data": LlmModelOut(**model).model_dump()}


@router.post("/models/{model_id}/enable")
def admin_enable_model(
    model_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.llm.model.enable")),
):
    before = _model_by_id(db, str(model_id))
    try:
        model = service.set_model_enabled(db, str(model_id), True, admin.id)
    except service.LLMConfigError as exc:
        _audit_failure(
            admin, request, "config.llm.model.enable", error_code=exc.code,
            target_id=str(model_id), target_name=before.get("name") if before else None,
        )
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.llm.model.enable", target_id=model["id"], target_name=model["name"],
        changes=audit_service.build_changes({"enabled": (before.get("enabled") if before else None, True)}),
    )
    db.commit()
    return {"data": LlmModelOut(**model).model_dump()}


@router.post("/models/{model_id}/disable")
def admin_disable_model(
    model_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.llm.model.disable")),
):
    before = _model_by_id(db, str(model_id))
    try:
        model = service.set_model_enabled(db, str(model_id), False, admin.id)
    except service.LLMConfigError as exc:
        _audit_failure(
            admin, request, "config.llm.model.disable", error_code=exc.code,
            target_id=str(model_id), target_name=before.get("name") if before else None,
        )
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.llm.model.disable", target_id=model["id"], target_name=model["name"],
        changes=audit_service.build_changes({
            "enabled": (before.get("enabled") if before else None, False),
            "used_by": ((before or {}).get("used_by"), model["used_by"]),
        }),
    )
    db.commit()
    return {"data": LlmModelOut(**model).model_dump()}


@router.post("/models/test")
def admin_test_model(
    data: LlmModelTestRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    result = service.test_model(db, data, user_id=admin.id)
    return {"data": LlmModelTestResult(**result).model_dump()}


# ---- 服务配置 ----

@router.get("/service-bindings")
def admin_get_service_bindings(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    return {"data": ServiceBindingsOut(**service.get_service_bindings(db)).model_dump()}


@router.put("/service-bindings")
def admin_update_service_bindings(
    data: ServiceBindingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.llm.binding.update")),
):
    before = service.get_service_bindings(db)
    try:
        result = service.update_service_bindings(db, data, admin.id)
    except service.LLMConfigError as exc:
        _audit_failure(admin, request, "config.llm.binding.update", error_code=exc.code, target_name="服务配置")
        raise _handle(exc)
    before_map = {s["service_type"]: (s["model"]["id"] if s["model"] else None) for s in before["services"]}
    after_map = {s["service_type"]: (s["model"]["id"] if s["model"] else None) for s in result["services"]}
    _audit_success(
        db, admin, request, "config.llm.binding.update", target_id=None, target_name="服务配置",
        changes=audit_service.build_changes({
            st: (before_map.get(st), after_map.get(st)) for st in before_map
        }),
    )
    db.commit()
    return {"data": ServiceBindingsOut(**result).model_dump()}


# ---- 辅助 ----

def _model_by_id(db: Session, model_id: str) -> dict | None:
    """读取模型当前输出（用于审计 before 快照）。不存在时返回 None。"""
    try:
        listing = service.list_models(db)
    except service.LLMConfigError:
        return None
    for item in listing["items"]:
        if item["id"] == model_id:
            return item
    return None


def _model_changes(before: dict | None, after: dict) -> list[dict]:
    fields = ("name", "model_type", "provider", "base_url", "model_name", "enabled", "has_api_key")
    changes = {}
    if before is None:
        for field in fields:
            changes[field] = (None, after[field])
    else:
        for field in fields:
            changes[field] = (before.get(field), after[field])
    return audit_service.build_changes(changes)
