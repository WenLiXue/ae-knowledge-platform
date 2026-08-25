"""人工确认服务（DD-19 §9、DD-05 §10）。

- 待确认：source/version 处于 PENDING_CONFIRMATION 的来源；
- 确认相关：校验元数据 → 写 document_metadata（MANUAL/MODEL 字段来源）→
  从 CHUNK 创建新任务 → 来源/版本回到 PROCESSING；
- 确认无关：来源 OFFLINE，版本 FAILED（人工判定不入库）；
- 重新分类：必须选择活动配置 revision 或形成新 input hash，
  否则复用已有结果（409），避免静默覆盖（DD-05 §9）。
并发覆盖由版本 row_version 乐观锁 + 行锁兜底；审计由 API 层写入。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.knowledge import DocumentVersion, KnowledgeSource
from ..db.models.rag import ClassificationResult
from ..db.models.task import ProcessingTask
from .config import load_classification_config
from .input_builder import compute_input_hash
from .schemas import ClassificationOutput
from .service import _upsert_metadata


class ConfirmationError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _task_key(version_id: uuid.UUID, task_type: str) -> str:
    return f"version:{version_id}:stage:{task_type.lower()}"


def _latest_result(session: Session, version_id: uuid.UUID) -> ClassificationResult | None:
    return session.execute(
        select(ClassificationResult)
        .where(ClassificationResult.version_id == version_id, ClassificationResult.status == "VALID")
        .order_by(ClassificationResult.created_at.desc())
    ).scalars().first()


def _ensure_open_task(session: Session, version_id: uuid.UUID, task_type: str) -> bool:
    """是否已存在该阶段的未终结任务（幂等防重）。"""
    existing = session.execute(
        select(ProcessingTask).where(
            ProcessingTask.idempotency_key == _task_key(version_id, task_type),
            ProcessingTask.status.in_(("PENDING", "RUNNING", "RETRY_WAIT")),
        )
    ).scalars().first()
    return existing is not None


def _pending_item(source: KnowledgeSource, version: DocumentVersion, result: ClassificationResult | None) -> dict:
    output = (result.output_json if result else None) or {}
    return {
        "source_id": str(source.id),
        "source_name": source.display_name,
        "source_type": source.source_type,
        "canonical_key": source.canonical_key,
        "version_id": str(version.id),
        "version_no": version.version_no,
        "row_version": version.row_version,
        "version_status": version.status,
        "classification": {
            "relevance": result.relevance if result else None,
            "relevance_confidence": result.relevance_confidence if result else None,
            "reason_summary": result.reason_summary if result else None,
            "missing_fields": (result.missing_fields or []) if result else [],
            "evidence": (result.evidence_json or []) if result else [],
            "output": output,
            "model_key": result.model_key if result else None,
            "prompt_revision": result.prompt_revision if result else None,
            "input_builder_revision": result.input_builder_revision if result else None,
            "config_revision": result.classification_config_revision if result else None,
            "input_hash": result.input_hash if result else None,
            "created_at": result.created_at.isoformat() if result and result.created_at else None,
        },
    }


# ---- 查询 ----

def list_pending(session: Session) -> list[dict]:
    sources = session.execute(
        select(KnowledgeSource)
        .where(KnowledgeSource.status == "PENDING_CONFIRMATION")
        .order_by(KnowledgeSource.updated_at.desc())
    ).scalars().all()
    items: list[dict] = []
    for source in sources:
        version = session.get(DocumentVersion, source.pending_version_id) if source.pending_version_id else None
        if version is None:
            continue
        items.append(_pending_item(source, version, _latest_result(session, version.id)))
    return items


def get_pending_detail(session: Session, version_id: uuid.UUID) -> dict | None:
    version = session.get(DocumentVersion, version_id)
    if version is None:
        return None
    source = session.get(KnowledgeSource, version.source_id)
    if source is None or source.status != "PENDING_CONFIRMATION":
        return None
    return _pending_item(source, version, _latest_result(session, version.id))


def _lock_version(session: Session, version_id: uuid.UUID, expected_row_version: int | None):
    version = session.execute(
        select(DocumentVersion).where(DocumentVersion.id == version_id).with_for_update()
    ).scalar_one_or_none()
    if version is None:
        raise ConfirmationError("NOT_FOUND", "版本不存在", status=404)
    if expected_row_version is not None and version.row_version != expected_row_version:
        raise ConfirmationError("VERSION_CONFLICT", "版本已被其他操作修改，请刷新后重试", status=409)
    source = session.get(KnowledgeSource, version.source_id)
    if source is None:
        raise ConfirmationError("NOT_FOUND", "来源不存在", status=404)
    return version, source


def _ensure_pending(source: KnowledgeSource, version: DocumentVersion) -> None:
    if source.status != "PENDING_CONFIRMATION" or version.status != "PENDING_CONFIRMATION":
        raise ConfirmationError(
            "NOT_PENDING", "该版本不在待确认状态", status=409
        )


# ---- 确认相关 ----

def _merged_output(
    session: Session,
    result: ClassificationResult | None,
    data,
) -> tuple[ClassificationOutput, set[str]]:
    """合并模型候选与人工覆盖；返回输出与覆盖字段集合。"""
    if result is not None and result.output_json:
        base = ClassificationOutput.model_validate(result.output_json)
    else:
        base = ClassificationOutput(relevance="RELEVANT", relevance_confidence=0.0, reason_summary="人工确认")

    overridden: set[str] = set()
    mapping = {
        "product_code": "product_code",
        "product_version_code": "product_version_code",
        "document_type_code": "document_type_code",
        "product_form_code": "product_form_code",
        "module_name": "module_name",
        "business_topic": "business_topic",
        "summary": "summary",
    }
    for attr, _ in mapping.items():
        value = getattr(data, attr)
        if value is not None:
            setattr(base, attr, value)
            overridden.add(attr)
    if data.is_domestic is not None:
        base.is_domestic = data.is_domestic
        overridden.add("is_domestic")
    if data.keywords is not None:
        base.keywords = data.keywords
        overridden.add("keywords")

    # 校验人工提供的 code 属于启用目录（AC-CLS-003）
    taxonomy = load_classification_config(session).taxonomy
    allowed = {
        "product_code": {str(p["code"]) for p in taxonomy.get("products") or []},
        "product_version_code": {str(v["code"]) for v in taxonomy.get("product_versions") or []},
        "document_type_code": {str(t["code"]) for t in taxonomy.get("document_types") or []},
        "product_form_code": {str(f["code"]) for f in taxonomy.get("product_forms") or []},
    }
    for attr in ("product_code", "product_version_code", "document_type_code", "product_form_code"):
        code = getattr(base, attr)
        if code is not None and code not in allowed[attr]:
            raise ConfirmationError("UNKNOWN_CODE", f"{attr} 不在启用 taxonomy 中: {code}", status=422)
    return base, overridden


def confirm_relevant(
    session: Session,
    version_id: uuid.UUID,
    data,
    *,
    user_id: uuid.UUID | None,
) -> dict:
    """确认相关：写 metadata（MANUAL/MODEL）并从 CHUNK 创建任务。"""
    version, source = _lock_version(session, version_id, data.expected_row_version)
    _ensure_pending(source, version)

    result = _latest_result(session, version.id)
    output, overridden = _merged_output(session, result, data)
    _upsert_metadata(
        session,
        version_id=version.id,
        result_id=result.id if result else None,
        output=output,
        taxonomy=load_classification_config(session).taxonomy,
        overridden=overridden,
    )

    if not _ensure_open_task(session, version.id, "CHUNK"):
        session.add(
            ProcessingTask(
                task_type="CHUNK",
                status="PENDING",
                idempotency_key=_task_key(version.id, "CHUNK"),
                scheduled_at=_now(),
                source_id=version.source_id,
                version_id=version.id,
                payload={"source_id": str(version.source_id), "version_id": str(version.id), "reason": "MANUAL_CONFIRM_RELEVANT"},
                priority=100,
                max_attempts=3,
                created_by_user_id=user_id,
            )
        )

    version.status = "PROCESSING"
    version.processing_stage = None
    version.row_version += 1
    source.status = "PROCESSING"
    source.update_status = "IDLE"
    session.flush()
    return _pending_item(source, version, _latest_result(session, version.id))


# ---- 确认无关 ----

def confirm_irrelevant(
    session: Session,
    version_id: uuid.UUID,
    data,
    *,
    user_id: uuid.UUID | None,
) -> dict:
    version, source = _lock_version(session, version_id, data.expected_row_version)
    _ensure_pending(source, version)
    version.status = "FAILED"
    version.error_code = "CLASSIFIED_IRRELEVANT"
    version.error_summary = "人工确认与平台知识无关，不入库"
    version.processing_stage = None
    version.row_version += 1
    source.status = "OFFLINE"
    source.offline_reason = data.reason or "人工确认无关"
    source.offlined_at = _now()
    session.flush()
    return _pending_item(source, version, _latest_result(session, version.id))


# ---- 重新分类 ----

def schedule_reclassify(
    session: Session,
    version_id: uuid.UUID,
    data,
    *,
    user_id: uuid.UUID | None,
) -> dict:
    """创建重新分类任务（DD-19 §9）。必须形成新 input_hash，否则 409。"""
    version, source = _lock_version(session, version_id, None)
    if source.status not in ("PENDING_CONFIRMATION", "FAILED") and version.status not in (
        "PENDING_CONFIRMATION",
        "FAILED",
    ):
        raise ConfirmationError("NOT_RECLASSIFIABLE", "该版本不允许重新分类", status=409)

    config = load_classification_config(session)
    if data.config_revision is not None and data.config_revision != config.config_revision:
        raise ConfirmationError(
            "CONFIG_NOT_ACTIVE", "指定配置 revision 不是当前 ACTIVE 版本", status=422
        )

    # 计算将形成的 input_hash：与已有有效结果相同则复用，拒绝静默覆盖
    try:
        from ..llm.runtime import resolve_service_model

        resolved = resolve_service_model(session, "DOCUMENT_CLASSIFICATION")
    except Exception as exc:  # noqa: BLE001  # LLMConfigError 等配置错误原样返回
        code = getattr(exc, "code", "CONFIG_ERROR")
        message = getattr(exc, "message", str(exc))
        raise ConfirmationError(code, message, status=getattr(exc, "status", 422)) from exc

    prospective_hash = compute_input_hash(
        content_sha256=version.content_sha256,
        config_revision=config.config_revision,
        model_key=resolved.model_config_id,
        model_revision=resolved.config_revision,
        prompt_revision=config.prompt_revision,
        input_builder_revision=config.input_builder_revision,
    )
    existing = _latest_result(session, version.id)
    if existing is not None and existing.input_hash == prospective_hash:
        raise ConfirmationError(
            "SAME_INPUT_HASH",
            "当前配置/模型将复用已有分类结果，无法重新分类；请先变更分类配置或模型绑定",
            status=409,
        )

    if _ensure_open_task(session, version.id, "CLASSIFY"):
        raise ConfirmationError("TASK_IN_PROGRESS", "已有分类任务在处理中", status=409)

    session.add(
        ProcessingTask(
            task_type="CLASSIFY",
            status="PENDING",
            idempotency_key=_task_key(version.id, "CLASSIFY"),
            scheduled_at=_now(),
            source_id=version.source_id,
            version_id=version.id,
            payload={"source_id": str(version.source_id), "version_id": str(version.id), "reason": "MANUAL_RECLASSIFY"},
            priority=100,
            max_attempts=3,
            created_by_user_id=user_id,
        )
    )
    version.status = "PROCESSING"
    version.processing_stage = "CLASSIFYING"
    version.row_version += 1
    source.status = "PROCESSING"
    source.update_status = "IDLE"
    session.flush()
    return _pending_item(source, version, _latest_result(session, version.id))
