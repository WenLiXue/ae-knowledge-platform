from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .db.session import get_db
from .knowledge import service
from .knowledge.service import RetryNotAllowed

router = APIRouter(prefix="/api/v1/knowledge-sources", tags=["knowledge-sources"])


@router.get("")
def list_knowledge_sources(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)) -> dict[str, object]:
    items, total = service.list_knowledge_sources(db, limit=limit, offset=offset)
    return {"data": {"items": items, "total": total, "limit": limit, "offset": offset}}


@router.get("/{source_id}")
def get_knowledge_source(source_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    item = service.get_knowledge_source(db, source_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SOURCE_NOT_FOUND", "source_id": str(source_id)},
        )
    return {"data": item}


@router.post("/{source_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_source(source_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        result = service.retry_source(db, source_id)
    except RetryNotAllowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SOURCE_NOT_RETRYABLE", "source_id": str(source_id)},
        )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SOURCE_NOT_FOUND", "source_id": str(source_id)},
        )
    return {"data": result}
