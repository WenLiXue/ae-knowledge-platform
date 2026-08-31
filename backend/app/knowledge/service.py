"""知识来源与应用服务：提交、查询、重试。事务边界由本层定义。"""

from __future__ import annotations

import uuid
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.catalog import DocumentType, Product, ProductVersion
from ..db.models.knowledge import DocumentVersion, FeishuSourceDetail, KnowledgeSource
from ..db.models.task import ProcessingTask
from ..db.models.rag import ClassificationResult, DocumentMetadata
from . import repository

FETCH_TASK_TYPE = "FETCH"
FETCH_STAGE = "FETCHING"
PARSE_TASK_TYPE = "PARSE"
PARSE_STAGE = "PARSING"


@dataclass
class SubmitItemIn:
    client_item_id: str
    resource_token: str
    resource_type: str
    canonical_key: str | None = None
    title: str | None = None
    revision: str | None = None
    modified_at: datetime | None = None
    owner_name: str | None = None
    original_url: str | None = None


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
        canonical_key = (item.canonical_key or item.resource_token).strip()
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
            resource_token=item.resource_token.strip(),
            original_url=item.original_url,
            last_seen_revision=item.revision,
            last_seen_modified_at=item.modified_at,
        )
        session.add(detail)

        version = DocumentVersion(
            source_id=source.id,
            version_no=1,
            status="PROCESSING",
            processing_stage=FETCH_STAGE,
            external_revision=item.revision,
            source_modified_at=item.modified_at,
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


def submit_manual_upload(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    filename: str,
    content_type: str | None,
    data: bytes,
    extracted_text: str,
    store,
) -> SubmitOutcome:
    """保存本地原文件及标准 raw 文本，并从 PARSE 阶段进入统一流水线。"""
    digest = hashlib.sha256(data).hexdigest()
    existing = repository.get_source_by_canonical_key(session, "MANUAL_UPLOAD", digest)
    item = SubmitItemIn(client_item_id=filename, resource_token=digest, resource_type="file")
    if existing is not None:
        return _build_duplicate_outcome(session, item, existing)

    source = KnowledgeSource(
        owner_user_id=owner_user_id,
        source_type="MANUAL_UPLOAD",
        canonical_key=digest,
        display_name=filename,
        status="PROCESSING",
        update_status="IDLE",
    )
    session.add(source)
    session.flush()
    version = DocumentVersion(
        source_id=source.id,
        version_no=1,
        status="PROCESSING",
        processing_stage=PARSE_STAGE,
        content_sha256=digest,
    )
    session.add(version)
    session.flush()

    suffix = filename.rsplit(".", 1)[-1].casefold()
    original_key = f"raw/{source.id}/{version.id}/original.{suffix}"
    normalized_key = f"raw/{source.id}/{version.id}/normalized.json"
    store.put(original_key, data)
    store.put(
        normalized_key,
        json.dumps(
            {
                "type": suffix,
                "raw_content": extracted_text,
                "filename": filename,
                "content_type": content_type,
                "original_object_key": original_key,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
    )
    version.raw_object_key = normalized_key

    task = ProcessingTask(
        task_type=PARSE_TASK_TYPE,
        status="PENDING",
        idempotency_key=_task_idempotency_key(version.id, PARSE_TASK_TYPE),
        scheduled_at=_utcnow(),
        source_id=source.id,
        version_id=version.id,
        payload={"source_id": str(source.id), "version_id": str(version.id), "reason": "UPLOAD"},
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
        session.rollback()
        existing = repository.get_source_by_canonical_key(session, "MANUAL_UPLOAD", digest)
        if existing is not None:
            return _build_duplicate_outcome(session, item, existing)
        raise
    return SubmitOutcome(
        client_item_id=filename,
        resource_token=digest,
        source_id=str(source.id),
        version_id=str(version.id),
        task_id=str(task.id),
        status="PROCESSING",
    )


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


def _list_classifications(session: Session, version_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """列表级轻量分类：产品/版本/文档类型（不含置信度、证据），避免逐来源 N+1。"""
    if not version_ids:
        return {}
    metas = {
        m.version_id: m
        for m in session.execute(
            select(DocumentMetadata).where(DocumentMetadata.version_id.in_(version_ids))
        ).scalars()
    }
    if not metas:
        return {}

    def _map(model, ids: set) -> dict:
        ids = {i for i in ids if i is not None}
        if not ids:
            return {}
        return {row.id: row for row in session.execute(select(model).where(model.id.in_(ids))).scalars()}

    products = _map(Product, {m.product_id for m in metas.values()})
    versions = _map(ProductVersion, {m.product_version_id for m in metas.values()})
    doc_types = _map(DocumentType, {m.document_type_id for m in metas.values()})

    out: dict[uuid.UUID, dict] = {}
    for vid, meta in metas.items():
        product = products.get(meta.product_id) if meta.product_id else None
        pv = versions.get(meta.product_version_id) if meta.product_version_id else None
        doc_type = doc_types.get(meta.document_type_id) if meta.document_type_id else None
        out[vid] = {
            "product_code": product.code if product else None,
            "product_name": product.name if product else None,
            "product_version_code": pv.version_code if pv else None,
            "document_type_code": doc_type.code if doc_type else None,
            "document_type_name": doc_type.name if doc_type else None,
        }
    return out


def list_knowledge_sources(session: Session, *, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, object]], int]:
    all_sources = repository.list_sources_with_detail(session)
    total = len(all_sources)
    items: list[dict[str, object]] = []
    version_ids: list[uuid.UUID] = []
    for source, detail in all_sources[max(offset, 0): max(offset, 0) + min(max(limit, 1), 200)]:
        latest = repository.get_latest_version(session, source.id)
        task = repository.get_latest_task(session, source.id)
        if latest is not None:
            version_ids.append(latest.id)
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
    classifications = _list_classifications(session, version_ids)
    for item in items:
        version_id = item.get("version_id")
        item["classification"] = classifications.get(uuid.UUID(str(version_id))) if version_id else None
    return items, total


def get_knowledge_source(session: Session, source_id: uuid.UUID) -> dict[str, object] | None:
    source = repository.get_source(session, source_id)
    if source is None:
        return None
    detail = repository.get_source_detail(session, source_id)
    latest = repository.get_latest_version(session, source_id)
    task = repository.get_latest_task(session, source_id)
    classification = None
    if latest is not None:
        result = session.execute(
            select(ClassificationResult)
            .where(ClassificationResult.version_id == latest.id)
            .order_by(ClassificationResult.created_at.desc())
            .limit(1)
        ).scalars().first()
        metadata = session.get(DocumentMetadata, latest.id)
        if result is not None or metadata is not None:
            output = (result.output_json if result else None) or {}
            classification = {
                "relevance": result.relevance if result else None,
                "relevance_confidence": float(result.relevance_confidence) if result and result.relevance_confidence is not None else None,
                "reason_summary": result.reason_summary if result else None,
                "missing_fields": (result.missing_fields or []) if result else [],
                "evidence": (result.evidence_json or []) if result else [],
                "output": output,
                "model_key": result.model_key if result else None,
                "config_revision": result.classification_config_revision if result else None,
                "created_at": result.created_at.isoformat() if result and result.created_at else None,
                "metadata": {
                    "product_id": str(metadata.product_id) if metadata and metadata.product_id else None,
                    "product_version_id": str(metadata.product_version_id) if metadata and metadata.product_version_id else None,
                    "document_type_id": str(metadata.document_type_id) if metadata and metadata.document_type_id else None,
                    "product_form_id": str(metadata.product_form_id) if metadata and metadata.product_form_id else None,
                    "module_name": metadata.module_name if metadata else None,
                    "business_topic": metadata.business_topic if metadata else None,
                    "summary": metadata.summary if metadata else None,
                    "keywords": (metadata.keywords or []) if metadata else [],
                },
            }
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
        "classification": classification,
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
