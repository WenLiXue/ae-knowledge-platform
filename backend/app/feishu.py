from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .core.config import get_settings
from .db.session import get_db
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


# 演示数据：真实飞书文档发现 API 接入前，用固定样本验证页面链路。
# 已提交状态与 source_id 由数据库决定，不再来自内存字典。
_DOCUMENTS = [
    FeishuDocument(
        resource_token="wiki-hardware-spec",
        title="AE 产品硬件规格",
        resource_type=ResourceType.WIKI,
        modified_at=datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc),
        owner_name="测试团队",
    ),
    FeishuDocument(
        resource_token="docx-product-whitepaper",
        title="AE 产品白皮书",
        resource_type=ResourceType.DOCX,
        modified_at=datetime(2026, 8, 10, 7, 30, tzinfo=timezone.utc),
        owner_name="产品团队",
    ),
    FeishuDocument(
        resource_token="wiki-seg-cases",
        title="SEG 问题案件沉淀",
        resource_type=ResourceType.WIKI,
        modified_at=datetime(2026, 8, 8, 9, 15, tzinfo=timezone.utc),
        owner_name="SEG 支持团队",
    ),
]

_TITLE_BY_TOKEN = {doc.resource_token: doc.title for doc in _DOCUMENTS}


@router.get("/connection")
def get_connection() -> dict[str, object]:
    """Temporary connection contract until Feishu OAuth is integrated."""

    return {
        "data": {
            "connected": True,
            "provider": "feishu",
            "display_name": "当前用户",
            "mode": "mock",
        }
    }


@router.get("/documents")
def list_documents(
    query: str | None = Query(default=None, max_length=100),
    resource_type: Annotated[list[ResourceType] | None, Query()] = None,
    limit: int = Query(default=50, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    filtered = _DOCUMENTS
    if query:
        keyword = query.casefold()
        filtered = [item for item in filtered if keyword in item.title.casefold()]
    if resource_type:
        allowed = set(resource_type)
        filtered = [item for item in filtered if item.resource_type in allowed]

    tokens = [item.resource_token for item in filtered[:limit]]
    # 已提交状态以数据库为准：真实 token 存在非下线来源即视为已提交
    submitted_map = service.find_submitted_sources(db, tokens)

    items = [
        item.model_copy(
            update={
                "submitted": item.resource_token in submitted_map,
                "source_id": (
                    str(submitted_map[item.resource_token].id)
                    if item.resource_token in submitted_map
                    else None
                ),
            }
        )
        for item in filtered[:limit]
    ]
    return {"data": {"items": items, "next_cursor": None}}


@router.post("/documents/submit", status_code=status.HTTP_202_ACCEPTED)
def submit_documents(
    payload: SubmitRequest, db: Session = Depends(get_db)
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
    submit_items = [
        service.SubmitItemIn(
            client_item_id=item.client_item_id,
            resource_token=item.resource_token,
            resource_type=item.resource_type.value,
            title=_TITLE_BY_TOKEN.get(item.resource_token),
        )
        for item in payload.items
    ]
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
