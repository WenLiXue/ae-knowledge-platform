"""知识库配置与 LLM 配置管理 API（仅管理员）。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.deps import get_current_admin
from ..db.models.user import User
from ..db.session import get_db
from . import service
from .schemas import (
    DocumentTypeCreate,
    DocumentTypeOut,
    DocumentTypeUpdate,
    LLMConfig,
    LLMConfigOut,
    LLMConfigUpdate,
    LLMTestResult,
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
        major_version=v.major_version, minor_version=v.minor_version,
        release_date=v.release_date, status=v.status, sort_order=v.sort_order,
    )


# ---- 产品 ----

@router.get("/catalog/products")
def admin_list_products(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    return {"data": {"items": [ProductOut(**_catalog_dict(p)) for p in service.admin_list_products(db)]}}


@router.post("/catalog/products", status_code=201)
def admin_create_product(data: ProductCreate, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        return {"data": ProductOut(**_catalog_dict(service.create_product(db, data)))}
    except service.ConfigError as exc:
        raise _handle(exc)


@router.patch("/catalog/products/{product_id}")
def admin_update_product(product_id: UUID, data: ProductUpdate, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        return {"data": ProductOut(**_catalog_dict(service.update_product(db, product_id, data)))}
    except service.ConfigError as exc:
        raise _handle(exc)


@router.post("/catalog/products/{product_id}/disable")
def admin_disable_product(product_id: UUID, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        return {"data": ProductOut(**_catalog_dict(service.set_product_status(db, product_id, "DISABLED")))}
    except service.ConfigError as exc:
        raise _handle(exc)


@router.post("/catalog/products/{product_id}/enable")
def admin_enable_product(product_id: UUID, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        return {"data": ProductOut(**_catalog_dict(service.set_product_status(db, product_id, "ENABLED")))}
    except service.ConfigError as exc:
        raise _handle(exc)


# ---- 产品版本 ----

@router.get("/catalog/products/{product_id}/versions")
def admin_list_versions(product_id: UUID, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    return {"data": {"items": [_version_dict(v) for v in service.admin_list_product_versions(db, product_id)]}}


@router.post("/catalog/products/{product_id}/versions", status_code=201)
def admin_create_version(product_id: UUID, data: ProductVersionCreate, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        return {"data": _version_dict(service.create_product_version(db, product_id, data))}
    except service.ConfigError as exc:
        raise _handle(exc)


@router.patch("/catalog/versions/{version_id}")
def admin_update_version(version_id: UUID, data: ProductVersionUpdate, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        return {"data": _version_dict(service.update_product_version(db, version_id, data))}
    except service.ConfigError as exc:
        raise _handle(exc)


@router.post("/catalog/versions/{version_id}/disable")
def admin_disable_version(version_id: UUID, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        return {"data": _version_dict(service.set_product_version_status(db, version_id, "DISABLED"))}
    except service.ConfigError as exc:
        raise _handle(exc)


@router.post("/catalog/versions/{version_id}/enable")
def admin_enable_version(version_id: UUID, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        return {"data": _version_dict(service.set_product_version_status(db, version_id, "ENABLED"))}
    except service.ConfigError as exc:
        raise _handle(exc)


# ---- 文档类型 ----

@router.get("/catalog/document-types")
def admin_list_document_types(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    return {"data": {"items": [DocumentTypeOut(**_catalog_dict(t), description=t.description) for t in service.admin_list_document_types(db)]}}


@router.post("/catalog/document-types", status_code=201)
def admin_create_document_type(data: DocumentTypeCreate, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        t = service.create_document_type(db, data)
        return {"data": DocumentTypeOut(**_catalog_dict(t), description=t.description)}
    except service.ConfigError as exc:
        raise _handle(exc)


@router.patch("/catalog/document-types/{type_id}")
def admin_update_document_type(type_id: UUID, data: DocumentTypeUpdate, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        t = service.update_document_type(db, type_id, data)
        return {"data": DocumentTypeOut(**_catalog_dict(t), description=t.description)}
    except service.ConfigError as exc:
        raise _handle(exc)


@router.post("/catalog/document-types/{type_id}/disable")
def admin_disable_document_type(type_id: UUID, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        t = service.set_document_type_status(db, type_id, "DISABLED")
        return {"data": DocumentTypeOut(**_catalog_dict(t), description=t.description)}
    except service.ConfigError as exc:
        raise _handle(exc)


@router.post("/catalog/document-types/{type_id}/enable")
def admin_enable_document_type(type_id: UUID, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        t = service.set_document_type_status(db, type_id, "ENABLED")
        return {"data": DocumentTypeOut(**_catalog_dict(t), description=t.description)}
    except service.ConfigError as exc:
        raise _handle(exc)


# ---- 产品形态 ----

@router.get("/catalog/product-forms")
def admin_list_product_forms(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    return {"data": {"items": [ProductFormOut(**_catalog_dict(f)) for f in service.admin_list_product_forms(db)]}}


@router.post("/catalog/product-forms", status_code=201)
def admin_create_product_form(data: ProductFormCreate, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        return {"data": ProductFormOut(**_catalog_dict(service.create_product_form(db, data)))}
    except service.ConfigError as exc:
        raise _handle(exc)


@router.patch("/catalog/product-forms/{form_id}")
def admin_update_product_form(form_id: UUID, data: ProductFormUpdate, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        return {"data": ProductFormOut(**_catalog_dict(service.update_product_form(db, form_id, data)))}
    except service.ConfigError as exc:
        raise _handle(exc)


@router.post("/catalog/product-forms/{form_id}/disable")
def admin_disable_product_form(form_id: UUID, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        return {"data": ProductFormOut(**_catalog_dict(service.set_product_form_status(db, form_id, "DISABLED")))}
    except service.ConfigError as exc:
        raise _handle(exc)


@router.post("/catalog/product-forms/{form_id}/enable")
def admin_enable_product_form(form_id: UUID, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        return {"data": ProductFormOut(**_catalog_dict(service.set_product_form_status(db, form_id, "ENABLED")))}
    except service.ConfigError as exc:
        raise _handle(exc)


# ---- 来源优先级 ----

@router.get("/source-priorities")
def admin_get_source_priorities(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    return {"data": {"items": [
        SourcePriorityOut(source_code=sp.source_code, display_name=sp.display_name, priority=sp.priority, status=sp.status)
        for sp in service.list_source_priorities(db)
    ]}}


@router.patch("/source-priorities")
def admin_update_source_priorities(data: SourcePrioritiesUpdate, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    try:
        rows = service.update_source_priorities(db, data.items)
    except service.ConfigError as exc:
        raise _handle(exc)
    return {"data": {"items": [
        SourcePriorityOut(source_code=sp.source_code, display_name=sp.display_name, priority=sp.priority, status=sp.status)
        for sp in rows
    ]}}


# ---- LLM 配置 ----

@router.get("/llm-config")
def admin_get_llm_config(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    data = service.get_llm_config(db)
    cfg = LLMConfig.model_validate(data["config"])
    return {"data": LLMConfigOut(**cfg.model_dump(), has_api_key=data["has_api_key"]).model_dump()}


@router.put("/llm-config")
def admin_update_llm_config(data: LLMConfigUpdate, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    result = service.update_llm_config(db, data, admin.id)
    cfg = LLMConfig.model_validate(result["config"])
    return {"data": LLMConfigOut(**cfg.model_dump(), has_api_key=result["has_api_key"]).model_dump()}


@router.post("/llm-config/test")
def admin_test_llm_config(data: LLMConfigUpdate, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    result = service.test_llm_config(db, data)
    return {"data": LLMTestResult(**result).model_dump()}
