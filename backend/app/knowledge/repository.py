"""知识来源与任务的数据访问层。只负责查询与持久化，不承载业务规则。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.knowledge import DocumentVersion, FeishuSourceDetail, KnowledgeSource
from ..db.models.task import ProcessingTask

_OPEN_TASK_STATUSES = ("PENDING", "RUNNING", "RETRY_WAIT")


def get_source_by_canonical_key(
    session: Session, source_type: str, canonical_key: str, include_offline: bool = False
) -> KnowledgeSource | None:
    """按规范化键查询来源；默认排除已下线来源。"""
    stmt = select(KnowledgeSource).where(
        KnowledgeSource.source_type == source_type,
        KnowledgeSource.canonical_key == canonical_key,
    )
    if not include_offline:
        stmt = stmt.where(KnowledgeSource.status != "OFFLINE")
    return session.execute(stmt).scalars().first()


def find_sources_by_tokens(session: Session, tokens: list[str]) -> dict[str, KnowledgeSource]:
    """按飞书 token 批量查询非下线来源，返回 {canonical_key: source}。"""
    if not tokens:
        return {}
    rows = session.execute(
        select(KnowledgeSource).where(
            KnowledgeSource.source_type == "FEISHU",
            KnowledgeSource.canonical_key.in_(tokens),
            KnowledgeSource.status != "OFFLINE",
        )
    ).scalars().all()
    return {source.canonical_key: source for source in rows}


def get_source(session: Session, source_id: uuid.UUID) -> KnowledgeSource | None:
    return session.get(KnowledgeSource, source_id)


def get_source_detail(session: Session, source_id: uuid.UUID) -> FeishuSourceDetail | None:
    return session.get(FeishuSourceDetail, source_id)


def get_latest_version(session: Session, source_id: uuid.UUID) -> DocumentVersion | None:
    return session.execute(
        select(DocumentVersion)
        .where(DocumentVersion.source_id == source_id)
        .order_by(DocumentVersion.version_no.desc())
        .limit(1)
    ).scalars().first()


def list_sources_with_detail(session: Session) -> list[tuple[KnowledgeSource, FeishuSourceDetail | None]]:
    """按创建时间倒序列出来源及其飞书详情（未接飞书时 detail 可为空）。"""
    return session.execute(
        select(KnowledgeSource, FeishuSourceDetail)
        .outerjoin(FeishuSourceDetail, FeishuSourceDetail.source_id == KnowledgeSource.id)
        .order_by(KnowledgeSource.created_at.desc())
    ).all()


def get_open_task(session: Session, idempotency_key: str) -> ProcessingTask | None:
    """查询指定幂等键下仍处于未终结状态的任务。"""
    return session.execute(
        select(ProcessingTask).where(
            ProcessingTask.idempotency_key == idempotency_key,
            ProcessingTask.status.in_(_OPEN_TASK_STATUSES),
        )
    ).scalars().first()


def get_latest_task(session: Session, source_id: uuid.UUID) -> ProcessingTask | None:
    return session.execute(
        select(ProcessingTask)
        .where(ProcessingTask.source_id == source_id)
        .order_by(ProcessingTask.created_at.desc(), ProcessingTask.id.desc())
        .limit(1)
    ).scalars().first()
