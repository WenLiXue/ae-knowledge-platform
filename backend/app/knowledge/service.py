"""知识来源与应用服务：提交、查询、重试。事务边界由本层定义。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.models.knowledge import DocumentVersion, FeishuSourceDetail, KnowledgeSource
from ..db.models.task import ProcessingTask
from . import repository

FETCH_TASK_TYPE = "FETCH"
FETCH_STAGE = "FETCHING"


@dataclass
class SubmitItemIn:
    client_item_id: str
    resource_token: str
    resource_type: str
    title: str | None = None


@dataclass
class SubmitOutcome:
    client_item_id: str
    resource_token: str
    source_id: str
    version_id: str | None
    task_id: str | None
    status: str
    duplicate: bool = False


class RetryNotAllowed(Exception):
    """来源当前状态不允许手动重试。"""


def _task_idempotency_key(version_id: uuid.UUID, task_type: str) -> str:
    # DD-04 §6.1：version:{version_id}:stage:{stage_name}
    return f"version:{version_id}:stage:{task_type.lower()}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _source_display_source(source: KnowledgeSource) -> dict[str, object]:
    return {
        "source_id": str(source.id),
        "resource_token": None,
        "resource_type": None,
        "display_name": source.display_name,
        "status": source.status,
        "update_status": source.update_status,
        "created_at": source.created_at.isoformat() if source.created_at else None,
    }


def find_submitted_sources(session: Session, tokens: list[str]) -> dict[str, KnowledgeSource]:
    """供文档发现接口使用：返回 token → 非下线来源 的映射。"""
    return repository.find_sources_by_tokens(session, tokens)


def submit_feishu_sources(
    session: Session, items: list[SubmitItemIn], owner_user_id: uuid.UUID
) -> list[SubmitOutcome]:
    """批量提交飞书来源。

    幂等规则（DD-02 §14.2 / DD-03 §9.1）：
    - 同一 canonical 键只允许一个非下线来源（数据库部分唯一索引兜底）；
    - 已存在来源时返回已有来源摘要，不重复建源，不改变所有者；
    - 单项独立事务，单项失败不影响其他已成功项。
    """
    outcomes: list[SubmitOutcome] = []

    for item in items:
        canonical_key = item.resource_token.strip()
        existing = repository.get_source_by_canonical_key(session, "FEISHU", canonical_key)
        if existing is not None:
            outcomes.append(_build_duplicate_outcome(session, item, existing))
            continue

        source = KnowledgeSource(
            owner_user_id=owner_user_id,
            source_type="FEISHU",
            canonical_key=canonical_key,
            display_name=item.title or canonical_key,
            status="PROCESSING",
            update_status="IDLE",
        )
        session.add(source)
        session.flush()

        detail = FeishuSourceDetail(
            source_id=source.id,
            resource_type=item.resource_type.upper(),
            resource_token=canonical_key,
        )
        session.add(detail)

        version = DocumentVersion(
            source_id=source.id,
            version_no=1,
            status="PROCESSING",
            processing_stage=FETCH_STAGE,
        )
        session.add(version)
        session.flush()

        task = ProcessingTask(
            task_type=FETCH_TASK_TYPE,
            status="PENDING",
            idempotency_key=_task_idempotency_key(version.id, FETCH_TASK_TYPE),
            # 显式用 Python 时钟设置，与 Worker 领取时的时钟保持一致（避免 DB/Python 时钟漂移）
            scheduled_at=_utcnow(),
            source_id=source.id,
            version_id=version.id,
            payload={
                "source_id": str(source.id),
                "version_id": str(version.id),
                "reason": "INITIAL",
            },
            priority=100,
            max_attempts=3,
            created_by_user_id=owner_user_id,
        )
        session.add(task)
        session.flush()

        source.pending_version_id = version.id

        try:
            session.commit()
        except IntegrityError:
            # 并发提交同一 token：唯一约束冲突 → 回滚并返回已存在来源
            session.rollback()
            existing = repository.get_source_by_canonical_key(session, "FEISHU", canonical_key)
            if existing is not None:
                outcomes.append(_build_duplicate_outcome(session, item, existing))
                continue
            raise

        outcomes.append(
            SubmitOutcome(
                client_item_id=item.client_item_id,
                resource_token=canonical_key,
                source_id=str(source.id),
                version_id=str(version.id),
                task_id=str(task.id),
                status="PROCESSING",
                duplicate=False,
            )
        )

    return outcomes


def _build_duplicate_outcome(
    session: Session, item: SubmitItemIn, existing: KnowledgeSource
) -> SubmitOutcome:
    latest = repository.get_latest_version(session, existing.id)
    task = repository.get_latest_task(session, existing.id)
    return SubmitOutcome(
        client_item_id=item.client_item_id,
        resource_token=item.resource_token,
        source_id=str(existing.id),
        version_id=str(latest.id) if latest else None,
        task_id=str(task.id) if task else None,
        status=existing.status,
        duplicate=True,
    )


def list_knowledge_sources(session: Session) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for source, detail in repository.list_sources_with_detail(session):
        latest = repository.get_latest_version(session, source.id)
        task = repository.get_latest_task(session, source.id)
        items.append(
            {
                **_source_display_source(source),
                "resource_token": detail.resource_token if detail else None,
                "resource_type": detail.resource_type if detail else None,
                "version_id": str(latest.id) if latest else None,
                "version_status": latest.status if latest else None,
                "task_id": str(task.id) if task else None,
                "task_status": task.status if task else None,
            }
        )
    return items


def get_knowledge_source(session: Session, source_id: uuid.UUID) -> dict[str, object] | None:
    source = repository.get_source(session, source_id)
    if source is None:
        return None
    detail = repository.get_source_detail(session, source_id)
    latest = repository.get_latest_version(session, source_id)
    task = repository.get_latest_task(session, source_id)
    return {
        **_source_display_source(source),
        "resource_token": detail.resource_token if detail else None,
        "resource_type": detail.resource_type if detail else None,
        "current_version_id": str(source.current_version_id) if source.current_version_id else None,
        "pending_version_id": str(source.pending_version_id) if source.pending_version_id else None,
        "version_id": str(latest.id) if latest else None,
        "version_status": latest.status if latest else None,
        "processing_stage": latest.processing_stage if latest else None,
        "task_id": str(task.id) if task else None,
        "task_status": task.status if task else None,
        "last_error_code": task.last_error_code if task else None,
        "last_error_summary": task.last_error_summary if task else None,
    }


def retry_source(session: Session, source_id: uuid.UUID) -> dict[str, object] | None:
    """手动重试失败来源（DD-02 §14.3）：创建新任务并通过 parent_task_id 关联旧任务。"""
    source = repository.get_source(session, source_id)
    if source is None:
        return None

    latest = repository.get_latest_version(session, source_id)
    latest_task = repository.get_latest_task(session, source_id)

    retryable = source.status == "FAILED" or (
        latest is not None and latest.status == "FAILED"
    ) or (
        latest_task is not None and latest_task.status == "FAILED"
    )
    if not retryable:
        raise RetryNotAllowed(str(source_id))

    task_type = latest_task.task_type if latest_task and latest_task.task_type else FETCH_TASK_TYPE
    stage = (
        latest.processing_stage
        if latest and latest.processing_stage
        else (FETCH_STAGE if task_type == FETCH_TASK_TYPE else None)
    )
    version_id = latest.id if latest else None
    idem_key = (
        _task_idempotency_key(version_id, task_type)
        if version_id is not None
        else f"source:{source_id}:retry"
    )

    # 幂等：同幂等键下已存在未终结任务则直接返回
    open_task = repository.get_open_task(session, idem_key)
    if open_task is not None:
        return {
            **_source_display_source(source),
            "task_id": str(open_task.id),
            "task_status": open_task.status,
            "retry_created": False,
        }

    new_task = ProcessingTask(
        task_type=task_type,
        status="PENDING",
        idempotency_key=idem_key,
        scheduled_at=_utcnow(),
        source_id=source_id,
        version_id=version_id,
        parent_task_id=latest_task.id if latest_task else None,
        payload={
            "source_id": str(source_id),
            "version_id": str(version_id) if version_id else None,
            "reason": "MANUAL_RETRY",
        },
        priority=100,
        max_attempts=3,
        created_by_user_id=source.owner_user_id,
    )
    session.add(new_task)

    source.status = "PROCESSING"
    source.update_status = "IDLE"
    if latest is not None:
        latest.status = "PROCESSING"
        latest.processing_stage = stage
        latest.error_code = None
        latest.error_summary = None
        source.pending_version_id = latest.id
    session.commit()

    return {
        **_source_display_source(source),
        "task_id": str(new_task.id),
        "task_status": new_task.status,
        "retry_created": True,
    }
