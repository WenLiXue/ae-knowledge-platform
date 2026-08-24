from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth.deps import get_optional_feishu_token
from .core.config import get_settings
from .db.session import get_db
from .feishu_provider.base import AUTH, NOT_FOUND, FeishuError
from .feishu_provider.factory import get_feishu_provider
from .knowledge import service

router = APIRouter(prefix="/api/v1/feishu", tags=["feishu"])


class ResourceType(StrEnum):
    WIKI = "wiki"
    DOCX = "docx"


class FeishuDocument(BaseModel):
    resource_token: str
    title: str
    resource_type: ResourceType
    modified_at: datetime
    owner_name: str
    submitted: bool = False
    source_id: str | None = None
    url: str | None = None


class SubmitItem(BaseModel):
    client_item_id: str = Field(min_length=1, max_length=100)
    resource_token: str = Field(min_length=1, max_length=200)
    resource_type: ResourceType


class SubmitRequest(BaseModel):
    items: list[SubmitItem] = Field(min_length=1, max_length=50)


class SubmitResult(BaseModel):
    client_item_id: str
    resource_token: str
    source_id: str
    version_id: str | None
    task_id: str | None
    status: str
    duplicate: bool = False


def _map_feishu_error(exc: FeishuError) -> HTTPException:
    if exc.category == NOT_FOUND:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": exc.message},
        )
    if exc.category == AUTH:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": exc.code, "message": exc.message},
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"code": exc.code, "message": exc.message},
    )


@router.get("/connection")
def get_connection() -> dict[str, object]:
    """查询飞书绑定与授权可用状态（OAuth 接入前为占位）。"""

    return {
        "data": {
            "connected": True,
            "provider": "feishu",
            "display_name": "当前用户",
            "mode": get_settings().feishu_provider,
        }
    }


@router.get("/documents")
def list_documents(
    query: str | None = Query(default=None, max_length=100),
    resource_type: Annotated[list[ResourceType] | None, Query()] = None,
    limit: int = Query(default=50, ge=1, le=50),
    page_token: str | None = Query(default=None),
    user_access_token: str | None = Depends(get_optional_feishu_token),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    provider = get_feishu_provider()
    resource_types = [r.value for r in resource_type] if resource_type else None
    try:
        result = provider.list_documents(
            user_access_token=user_access_token,
            query=query,
            resource_types=resource_types,
            page_token=page_token,
            limit=limit,
        )
    except FeishuError as exc:
        raise _map_feishu_error(exc) from exc

    tokens = [d.canonical_token or d.resource_token for d in result.items]
    submitted_map = service.find_submitted_sources(db, tokens)

    items: list[FeishuDocument] = []
    for doc in result.items:
        token = doc.canonical_token or doc.resource_token
        try:
            rtype = ResourceType(doc.resource_type)
        except ValueError:
            continue  # 仅展示 wiki/docx
        submitted = token in submitted_map
        items.append(
            FeishuDocument(
                resource_token=doc.resource_token,
                title=doc.title,
                resource_type=rtype,
                modified_at=doc.modified_at or datetime(1970, 1, 1, tzinfo=timezone.utc),
                owner_name=doc.owner_name or "",
                submitted=submitted,
                source_id=str(submitted_map[token].id) if submitted else None,
                url=doc.url,
            )
        )
    return {"data": {"items": items, "next_cursor": result.next_cursor}}


@router.post("/documents/submit", status_code=status.HTTP_202_ACCEPTED)
def submit_documents(
    payload: SubmitRequest,
    user_access_token: str | None = Depends(get_optional_feishu_token),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    # 同一次请求内不允许重复提交同一 token
    seen: set[str] = set()
    for item in payload.items:
        if item.resource_token in seen:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "DUPLICATE_SUBMISSION", "resource_token": item.resource_token},
            )
        seen.add(item.resource_token)

    owner_user_id = uuid.UUID(get_settings().default_owner_user_id)
    provider = get_feishu_provider()

    submit_items: list[service.SubmitItemIn] = []
    for item in payload.items:
        try:
            meta = provider.get_metadata(
                user_access_token, item.resource_token, item.resource_type.value
            )
        except FeishuError as exc:
            raise _map_feishu_error(exc) from exc
        submit_items.append(
            service.SubmitItemIn(
                client_item_id=item.client_item_id,
                resource_token=item.resource_token,
                resource_type=item.resource_type.value,
                title=meta.title,
                revision=meta.revision,
                modified_at=meta.modified_at,
                owner_name=meta.owner_name,
            )
        )

    outcomes = service.submit_feishu_sources(db, submit_items, owner_user_id)
    results = [
        SubmitResult(
            client_item_id=outcome.client_item_id,
            resource_token=outcome.resource_token,
            source_id=outcome.source_id,
            version_id=outcome.version_id,
            task_id=outcome.task_id,
            status=outcome.status,
            duplicate=outcome.duplicate,
        )
        for outcome in outcomes
    ]
    return {"data": {"items": results}}
