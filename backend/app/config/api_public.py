"""目录查询 API（public，仅返回启用态，供查询/导入页使用）。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db.session import get_db
from . import service
from .schemas import (
    DocumentTypeOut,
    ProductFormOut,
    ProductOut,
    ProductVersionOut,
    SourcePriorityOut,
)

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


def _catalog_dict(obj) -> dict:
    return {
        "id": str(obj.id),
        "code": obj.code,
        "name": obj.name,
        "status": obj.status,
        "sort_order": obj.sort_order,
    }


@router.get("/products")
def get_products(db: Session = Depends(get_db)) -> dict:
    return {"data": {"items": [ProductOut(**_catalog_dict(p)) for p in service.list_products(db)]}}


@router.get("/products/{product_id}/versions")
def get_product_versions(product_id: UUID, db: Session = Depends(get_db)) -> dict:
    items = [
        ProductVersionOut(
            id=str(v.id),
            product_id=str(v.product_id),
            version_code=v.version_code,
            major_version=v.major_version,
            minor_version=v.minor_version,
            release_date=v.release_date,
            status=v.status,
            sort_order=v.sort_order,
        )
        for v in service.list_product_versions(db, product_id)
    ]
    return {"data": {"items": items}}


@router.get("/document-types")
def get_document_types(db: Session = Depends(get_db)) -> dict:
    return {
        "data": {
            "items": [DocumentTypeOut(**_catalog_dict(t), description=t.description) for t in service.list_document_types(db)]
        }
    }


@router.get("/product-forms")
def get_product_forms(db: Session = Depends(get_db)) -> dict:
    return {"data": {"items": [ProductFormOut(**_catalog_dict(f)) for f in service.list_product_forms(db)]}}


@router.get("/source-priorities")
def get_source_priorities(db: Session = Depends(get_db)) -> dict:
    items = [
        SourcePriorityOut(
            source_code=sp.source_code, display_name=sp.display_name,
            priority=sp.priority, status=sp.status,
        )
        for sp in service.list_source_priorities(db)
    ]
    return {"data": {"items": items}}
