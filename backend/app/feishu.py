from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth.deps import get_current_user, get_required_feishu_token
from .core.config import get_settings
from .db.models.user import User
from .db.session import get_db
from .feishu_provider.base import AUTH, NOT_FOUND, PERMISSION, FeishuError
from .feishu_provider.factory import get_feishu_provider
from .knowledge import service

router = APIRouter(prefix="/api/v1/feishu", tags=["feishu"])
logger = logging.getLogger(__name__)


class ResourceType(StrEnum):
    WIKI = "wiki"
    DOCX = "docx"
    SHEET = "sheet"
    FILE = "file"


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
    url: str | None = None


class SubmitRequest(BaseModel):
    items: list[SubmitItem] = Field(min_length=1, max_length=50)


class LinkSubmitRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=20)


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
    if exc.category == PERMISSION:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": exc.code, "message": exc.message},
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"code": exc.code, "message": exc.message},
    )


@router.get("/connection")
def get_connection(
    user: User = Depends(get_current_user),
    _user_access_token: str = Depends(get_required_feishu_token),
) -> dict[str, object]:
    """查询当前登录用户的飞书授权可用状态。"""
    return {
        "data": {
            "connected": True,
            "provider": "feishu",
            "display_name": user.display_name,
            "mode": get_settings().feishu_provider,
        }
    }


@router.get("/documents")
def list_documents(
    query: str | None = Query(default=None, max_length=100),
    resource_type: Annotated[list[ResourceType] | None, Query()] = None,
    limit: int = Query(default=50, ge=1, le=50),
    page_token: str | None = Query(default=None),
    user_access_token: str = Depends(get_required_feishu_token),
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
    user_access_token: str = Depends(get_required_feishu_token),
    user: User = Depends(get_current_user),
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

    # 来源归属请求者用户（Worker 后续使用其飞书授权读取正文）。
    owner_user_id = user.id
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
                original_url=item.url or meta.url,
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


@router.post("/documents/submit-links", status_code=status.HTTP_202_ACCEPTED)
def submit_document_links(
    payload: LinkSubmitRequest,
    user_access_token: str = Depends(get_required_feishu_token),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    provider = get_feishu_provider()
    items: list[service.SubmitItemIn] = []
    seen: set[str] = set()
    for raw_url in payload.urls:
        url = raw_url.strip()
        if not url:
            continue
        try:
            meta = provider.resolve_url(user_access_token, url)
        except FeishuError as exc:
            raise _map_feishu_error(exc) from exc
        if meta.resource_type not in {
            ResourceType.WIKI.value,
            ResourceType.DOCX.value,
            ResourceType.SHEET.value,
            ResourceType.FILE.value,
        }:
            logger.warning(
                "unsupported_feishu_resource",
                extra={
                    "url": url,
                    "resource_type": meta.resource_type,
                    "resource_token": meta.resource_token,
                    "node_token": meta.node_token,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail={
                    "code": "UNSUPPORTED_FEISHU_RESOURCE",
                    "message": f"该 Wiki 节点实际类型为 {meta.resource_type}，目前支持 Wiki、文档、电子表格及 PDF/DOCX/XLSX 附件。",
                },
            )
        token = meta.canonical_token or meta.resource_token
        if token in seen:
            continue
        seen.add(token)
        items.append(
            service.SubmitItemIn(
                client_item_id=url,
                resource_token=meta.resource_token,
                resource_type=meta.resource_type,
                canonical_key=token,
                original_url=meta.url or url,
                title=meta.title,
                revision=meta.revision,
                modified_at=meta.modified_at,
                owner_name=meta.owner_name,
            )
        )
    if not items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "EMPTY_LINKS", "message": "请至少输入一个有效的飞书链接。"},
        )
    outcomes = service.submit_feishu_sources(db, items, user.id)
    return {"data": {"items": [outcome.__dict__ for outcome in outcomes]}}
