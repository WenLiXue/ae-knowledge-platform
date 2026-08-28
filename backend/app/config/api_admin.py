"""知识库配置与 LLM 配置管理 API（登录用户可访问）。

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
from ..db.models.catalog import DocumentType, Product, ProductForm, ProductVersion, SourcePriority
from ..db.models.user import User
from ..db.session import get_db
from . import service
from .schemas import (
    DocumentTypeCreate,
    DocumentTypeOut,
    DocumentTypeUpdate,
    ProductCreate,
    ProductFormCreate,
    ProductFormOut,
    ProductFormUpdate,
    ProductOut,
    ProductUpdate,
    ProductVersionCreate,
    ProductVersionOut,
    ProductVersionUpdate,
    SourcePrioritiesUpdate,
    SourcePriorityOut,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-config"])


def _handle(exc: service.ConfigError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


def _catalog_dict(obj) -> dict:
    return {"id": str(obj.id), "code": obj.code, "name": obj.name, "status": obj.status, "sort_order": obj.sort_order}


def _version_dict(v) -> dict:
    return ProductVersionOut(
        id=str(v.id), product_id=str(v.product_id), version_code=v.version_code,
        big_version=v.big_version,
        release_date=v.release_date, status=v.status, sort_order=v.sort_order,
    )


def _audit_success(
    db: Session,
    admin: User,
    request: Request,
    action: str,
    *,
    target_type: str,
    target_id: str | None = None,
    target_name: str | None = None,
    changes: list[dict] | None = None,
    summary: str | None = None,
) -> None:
    audit_service.record_success(
        db,
        audit_service.success_event(
            user=admin,
            context=build_context(request),
            action=action,
            summary=summary or action,
            target_type=target_type,
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
    target_type: str,
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
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
        )
    )


# ---- 产品 ----

@router.get("/catalog/products")
def admin_list_products(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    return {"data": {"items": [ProductOut(**_catalog_dict(p)) for p in service.admin_list_products(db)]}}


@router.post("/catalog/products", status_code=201)
def admin_create_product(
    data: ProductCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.product.create")),
):
    try:
        p = service.create_product(db, data)
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.product.create", error_code=exc.code, target_type="PRODUCT")
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.product.create", target_type="PRODUCT",
        target_id=str(p.id), target_name=p.name,
        changes=audit_service.build_changes({
            "code": (None, p.code), "name": (None, p.name),
            "status": (None, p.status), "sort_order": (None, p.sort_order),
        }),
    )
    db.commit()
    return {"data": ProductOut(**_catalog_dict(p))}


@router.patch("/catalog/products/{product_id}")
def admin_update_product(
    product_id: UUID,
    data: ProductUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.product.update")),
):
    before = db.get(Product, product_id)
    try:
        p = service.update_product(db, product_id, data)
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.product.update", error_code=exc.code, target_type="PRODUCT", target_id=str(product_id), target_name=before.name if before else None)
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.product.update", target_type="PRODUCT",
        target_id=str(p.id), target_name=p.name,
        changes=audit_service.build_changes({
            "name": (before.name if before else None, p.name),
            "status": (before.status if before else None, p.status),
            "sort_order": (before.sort_order if before else None, p.sort_order),
        }),
    )
    db.commit()
    return {"data": ProductOut(**_catalog_dict(p))}


@router.post("/catalog/products/{product_id}/disable")
def admin_disable_product(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.product.disable")),
):
    before = db.get(Product, product_id)
    try:
        p = service.set_product_status(db, product_id, "DISABLED")
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.product.disable", error_code=exc.code, target_type="PRODUCT", target_id=str(product_id), target_name=before.name if before else None)
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.product.disable", target_type="PRODUCT",
        target_id=str(p.id), target_name=p.name,
        changes=audit_service.build_changes({"status": (before.status if before else None, p.status)}),
    )
    db.commit()
    return {"data": ProductOut(**_catalog_dict(p))}


@router.post("/catalog/products/{product_id}/enable")
def admin_enable_product(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.product.enable")),
):
    before = db.get(Product, product_id)
    try:
        p = service.set_product_status(db, product_id, "ENABLED")
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.product.enable", error_code=exc.code, target_type="PRODUCT", target_id=str(product_id), target_name=before.name if before else None)
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.product.enable", target_type="PRODUCT",
        target_id=str(p.id), target_name=p.name,
        changes=audit_service.build_changes({"status": (before.status if before else None, p.status)}),
    )
    db.commit()
    return {"data": ProductOut(**_catalog_dict(p))}


@router.delete("/catalog/products/{product_id}", status_code=204)
def admin_delete_product(
    product_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.product.delete")),
):
    before = db.get(Product, product_id)
    try:
        service.delete_product(db, product_id)
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.product.delete", error_code=exc.code, target_type="PRODUCT", target_id=str(product_id), target_name=before.name if before else None)
        raise _handle(exc)
    _audit_success(db, admin, request, "config.catalog.product.delete", target_type="PRODUCT", target_id=str(product_id), target_name=before.name if before else None)
    db.commit()


# ---- 产品版本 ----

@router.get("/catalog/products/{product_id}/versions")
def admin_list_versions(product_id: UUID, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    return {"data": {"items": [_version_dict(v) for v in service.admin_list_product_versions(db, product_id)]}}


@router.post("/catalog/products/{product_id}/versions", status_code=201)
def admin_create_version(
    product_id: UUID,
    data: ProductVersionCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.version.create")),
):
    try:
        v = service.create_product_version(db, product_id, data)
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.version.create", error_code=exc.code, target_type="PRODUCT_VERSION")
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.version.create", target_type="PRODUCT_VERSION",
        target_id=str(v.id), target_name=v.version_code,
        changes=audit_service.build_changes({
            "version_code": (None, v.version_code), "big_version": (None, v.big_version), "release_date": (None, v.release_date),
            "status": (None, v.status), "sort_order": (None, v.sort_order),
        }),
    )
    db.commit()
    return {"data": _version_dict(v)}


@router.patch("/catalog/versions/{version_id}")
def admin_update_version(
    version_id: UUID,
    data: ProductVersionUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.version.update")),
):
    before = db.get(ProductVersion, version_id)
    try:
        v = service.update_product_version(db, version_id, data)
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.version.update", error_code=exc.code, target_type="PRODUCT_VERSION", target_id=str(version_id), target_name=before.version_code if before else None)
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.version.update", target_type="PRODUCT_VERSION",
        target_id=str(v.id), target_name=v.version_code,
        changes=audit_service.build_changes({
            "version_code": (before.version_code if before else None, v.version_code),
            "big_version": (before.big_version if before else None, v.big_version),
            "release_date": (before.release_date if before else None, v.release_date),
            "status": (before.status if before else None, v.status),
            "sort_order": (before.sort_order if before else None, v.sort_order),
        }),
    )
    db.commit()
    return {"data": _version_dict(v)}


@router.post("/catalog/versions/{version_id}/disable")
def admin_disable_version(
    version_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.version.disable")),
):
    before = db.get(ProductVersion, version_id)
    try:
        v = service.set_product_version_status(db, version_id, "DISABLED")
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.version.disable", error_code=exc.code, target_type="PRODUCT_VERSION", target_id=str(version_id), target_name=before.version_code if before else None)
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.version.disable", target_type="PRODUCT_VERSION",
        target_id=str(v.id), target_name=v.version_code,
        changes=audit_service.build_changes({"status": (before.status if before else None, v.status)}),
    )
    db.commit()
    return {"data": _version_dict(v)}


@router.post("/catalog/versions/{version_id}/enable")
def admin_enable_version(
    version_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.version.enable")),
):
    before = db.get(ProductVersion, version_id)
    try:
        v = service.set_product_version_status(db, version_id, "ENABLED")
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.version.enable", error_code=exc.code, target_type="PRODUCT_VERSION", target_id=str(version_id), target_name=before.version_code if before else None)
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.version.enable", target_type="PRODUCT_VERSION",
        target_id=str(v.id), target_name=v.version_code,
        changes=audit_service.build_changes({"status": (before.status if before else None, v.status)}),
    )
    db.commit()
    return {"data": _version_dict(v)}


@router.delete("/catalog/versions/{version_id}", status_code=204)
def admin_delete_version(
    version_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.version.delete")),
):
    before = db.get(ProductVersion, version_id)
    try:
        service.delete_product_version(db, version_id)
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.version.delete", error_code=exc.code, target_type="PRODUCT_VERSION", target_id=str(version_id), target_name=before.version_code if before else None)
        raise _handle(exc)
    _audit_success(db, admin, request, "config.catalog.version.delete", target_type="PRODUCT_VERSION", target_id=str(version_id), target_name=before.version_code if before else None)
    db.commit()


# ---- 文档类型 ----

@router.get("/catalog/document-types")
def admin_list_document_types(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    return {"data": {"items": [DocumentTypeOut(**_catalog_dict(t), description=t.description) for t in service.admin_list_document_types(db)]}}


@router.post("/catalog/document-types", status_code=201)
def admin_create_document_type(
    data: DocumentTypeCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.document_type.create")),
):
    try:
        t = service.create_document_type(db, data)
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.document_type.create", error_code=exc.code, target_type="DOCUMENT_TYPE")
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.document_type.create", target_type="DOCUMENT_TYPE",
        target_id=str(t.id), target_name=t.name,
        changes=audit_service.build_changes({
            "code": (None, t.code), "name": (None, t.name),
            "description": (None, t.description), "status": (None, t.status), "sort_order": (None, t.sort_order),
        }),
    )
    db.commit()
    return {"data": DocumentTypeOut(**_catalog_dict(t), description=t.description)}


@router.patch("/catalog/document-types/{type_id}")
def admin_update_document_type(
    type_id: UUID,
    data: DocumentTypeUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.document_type.update")),
):
    before = db.get(DocumentType, type_id)
    try:
        t = service.update_document_type(db, type_id, data)
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.document_type.update", error_code=exc.code, target_type="DOCUMENT_TYPE", target_id=str(type_id), target_name=before.name if before else None)
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.document_type.update", target_type="DOCUMENT_TYPE",
        target_id=str(t.id), target_name=t.name,
        changes=audit_service.build_changes({
            "name": (before.name if before else None, t.name),
            "description": (before.description if before else None, t.description),
            "status": (before.status if before else None, t.status),
            "sort_order": (before.sort_order if before else None, t.sort_order),
        }),
    )
    db.commit()
    return {"data": DocumentTypeOut(**_catalog_dict(t), description=t.description)}


@router.post("/catalog/document-types/{type_id}/disable")
def admin_disable_document_type(
    type_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.document_type.disable")),
):
    before = db.get(DocumentType, type_id)
    try:
        t = service.set_document_type_status(db, type_id, "DISABLED")
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.document_type.disable", error_code=exc.code, target_type="DOCUMENT_TYPE", target_id=str(type_id), target_name=before.name if before else None)
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.document_type.disable", target_type="DOCUMENT_TYPE",
        target_id=str(t.id), target_name=t.name,
        changes=audit_service.build_changes({"status": (before.status if before else None, t.status)}),
    )
    db.commit()
    return {"data": DocumentTypeOut(**_catalog_dict(t), description=t.description)}


@router.post("/catalog/document-types/{type_id}/enable")
def admin_enable_document_type(
    type_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.document_type.enable")),
):
    before = db.get(DocumentType, type_id)
    try:
        t = service.set_document_type_status(db, type_id, "ENABLED")
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.document_type.enable", error_code=exc.code, target_type="DOCUMENT_TYPE", target_id=str(type_id), target_name=before.name if before else None)
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.document_type.enable", target_type="DOCUMENT_TYPE",
        target_id=str(t.id), target_name=t.name,
        changes=audit_service.build_changes({"status": (before.status if before else None, t.status)}),
    )
    db.commit()
    return {"data": DocumentTypeOut(**_catalog_dict(t), description=t.description)}


@router.delete("/catalog/document-types/{type_id}", status_code=204)
def admin_delete_document_type(
    type_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.document_type.delete")),
):
    before = db.get(DocumentType, type_id)
    try:
        service.delete_document_type(db, type_id)
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.document_type.delete", error_code=exc.code, target_type="DOCUMENT_TYPE", target_id=str(type_id), target_name=before.name if before else None)
        raise _handle(exc)
    _audit_success(db, admin, request, "config.catalog.document_type.delete", target_type="DOCUMENT_TYPE", target_id=str(type_id), target_name=before.name if before else None)
    db.commit()


# ---- 产品形态 ----

@router.get("/catalog/product-forms")
def admin_list_product_forms(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    return {"data": {"items": [ProductFormOut(**_catalog_dict(f)) for f in service.admin_list_product_forms(db)]}}


@router.post("/catalog/product-forms", status_code=201)
def admin_create_product_form(
    data: ProductFormCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.product_form.create")),
):
    try:
        f = service.create_product_form(db, data)
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.product_form.create", error_code=exc.code, target_type="PRODUCT_FORM")
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.product_form.create", target_type="PRODUCT_FORM",
        target_id=str(f.id), target_name=f.name,
        changes=audit_service.build_changes({
            "code": (None, f.code), "name": (None, f.name),
            "status": (None, f.status), "sort_order": (None, f.sort_order),
        }),
    )
    db.commit()
    return {"data": ProductFormOut(**_catalog_dict(f))}


@router.patch("/catalog/product-forms/{form_id}")
def admin_update_product_form(
    form_id: UUID,
    data: ProductFormUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.product_form.update")),
):
    before = db.get(ProductForm, form_id)
    try:
        f = service.update_product_form(db, form_id, data)
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.product_form.update", error_code=exc.code, target_type="PRODUCT_FORM", target_id=str(form_id), target_name=before.name if before else None)
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.product_form.update", target_type="PRODUCT_FORM",
        target_id=str(f.id), target_name=f.name,
        changes=audit_service.build_changes({
            "name": (before.name if before else None, f.name),
            "status": (before.status if before else None, f.status),
            "sort_order": (before.sort_order if before else None, f.sort_order),
        }),
    )
    db.commit()
    return {"data": ProductFormOut(**_catalog_dict(f))}


@router.post("/catalog/product-forms/{form_id}/disable")
def admin_disable_product_form(
    form_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.product_form.disable")),
):
    before = db.get(ProductForm, form_id)
    try:
        f = service.set_product_form_status(db, form_id, "DISABLED")
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.product_form.disable", error_code=exc.code, target_type="PRODUCT_FORM", target_id=str(form_id), target_name=before.name if before else None)
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.product_form.disable", target_type="PRODUCT_FORM",
        target_id=str(f.id), target_name=f.name,
        changes=audit_service.build_changes({"status": (before.status if before else None, f.status)}),
    )
    db.commit()
    return {"data": ProductFormOut(**_catalog_dict(f))}


@router.post("/catalog/product-forms/{form_id}/enable")
def admin_enable_product_form(
    form_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.product_form.enable")),
):
    before = db.get(ProductForm, form_id)
    try:
        f = service.set_product_form_status(db, form_id, "ENABLED")
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.product_form.enable", error_code=exc.code, target_type="PRODUCT_FORM", target_id=str(form_id), target_name=before.name if before else None)
        raise _handle(exc)
    _audit_success(
        db, admin, request, "config.catalog.product_form.enable", target_type="PRODUCT_FORM",
        target_id=str(f.id), target_name=f.name,
        changes=audit_service.build_changes({"status": (before.status if before else None, f.status)}),
    )
    db.commit()
    return {"data": ProductFormOut(**_catalog_dict(f))}


@router.delete("/catalog/product-forms/{form_id}", status_code=204)
def admin_delete_product_form(
    form_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.catalog.product_form.delete")),
):
    before = db.get(ProductForm, form_id)
    try:
        service.delete_product_form(db, form_id)
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.catalog.product_form.delete", error_code=exc.code, target_type="PRODUCT_FORM", target_id=str(form_id), target_name=before.name if before else None)
        raise _handle(exc)
    _audit_success(db, admin, request, "config.catalog.product_form.delete", target_type="PRODUCT_FORM", target_id=str(form_id), target_name=before.name if before else None)
    db.commit()


# ---- 来源优先级 ----

@router.get("/source-priorities")
def admin_get_source_priorities(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    return {"data": {"items": [
        SourcePriorityOut(source_code=sp.source_code, display_name=sp.display_name, priority=sp.priority, status=sp.status)
        for sp in service.list_source_priorities(db)
    ]}}


@router.patch("/source-priorities")
def admin_update_source_priorities(
    data: SourcePrioritiesUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_action("config.source_priority.update")),
):
    before_map = {sp.source_code: sp.priority for sp in service.list_source_priorities(db)}
    try:
        rows = service.update_source_priorities(db, data.items)
    except service.ConfigError as exc:
        _audit_failure(admin, request, "config.source_priority.update", error_code=exc.code, target_type="SOURCE_PRIORITY")
        raise _handle(exc)
    after_map = {sp.source_code: sp.priority for sp in rows}
    changes = audit_service.build_changes({
        code: (before_map.get(code), after_map.get(code)) for code in after_map
    })
    _audit_success(
        db, admin, request, "config.source_priority.update", target_type="SOURCE_PRIORITY",
        target_name="来源优先级", changes=changes,
    )
    db.commit()
    return {"data": {"items": [
        SourcePriorityOut(source_code=sp.source_code, display_name=sp.display_name, priority=sp.priority, status=sp.status)
        for sp in rows
    ]}}
