"""文档处理流水线。

阶段顺序对齐 DD-04 §5：FETCH → PARSE → CLASSIFY → CHUNK → EMBED → INDEX → FINALIZE。

- FETCH 通过 FeishuDocumentProvider 读取真实/模拟正文，raw 内容写入对象存储（本地实现），
  并记录 revision / modified_at；获取到的 revision 与已记录版本不一致时终止当前版本、
  创建新版本重新处理（DD-04 §6.2）。
- CLASSIFY 目前为确定性 mock 判定：token 含 uncertain → PENDING_CONFIRMATION，
  irrelevant → 来源 OFFLINE（明确无关）；其余视为相关继续流水线。
- 真实飞书 / LLM 分类 / 向量库接入后，以相同阶段契约替换各 handler。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.feishu import get_user_access_token
from ..db.models.knowledge import DocumentVersion, FeishuSourceDetail, KnowledgeSource
from ..db.models.task import ProcessingTask
from ..feishu_auth.base import FeishuOAuthClient
from ..feishu_provider.base import FeishuError, FeishuDocumentProvider

logger = logging.getLogger(__name__)

# 阶段任务类型 → 版本 processing_stage 值
STAGE_NAMES = {
    "FETCH": "FETCHING",
    "PARSE": "PARSING",
    "CLASSIFY": "CLASSIFYING",
    "CHUNK": "CHUNKING",
    "EMBED": "EMBEDDING",
    "INDEX": "INDEXING",
    "FINALIZE": "FINALIZING",
}

# 阶段链：完成当前阶段后创建的下一个任务类型
NEXT_STAGE = {
    "FETCH": "PARSE",
    "PARSE": "CLASSIFY",
    "CLASSIFY": "CHUNK",
    "CHUNK": "EMBED",
    "EMBED": "INDEX",
    "INDEX": "FINALIZE",
    "FINALIZE": None,
}


class PipelineError(Exception):
    """流水线阶段失败。category 对齐 DD-02 §8.2 错误分类。"""

    def __init__(self, category: str, code: str, message: str, *, retryable: bool):
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message
        self.retryable = retryable


def execute_stage(
    session: Session,
    task,
    *,
    provider: FeishuDocumentProvider,
    oauth_client: FeishuOAuthClient,
    store,
) -> str | None:
    """执行一个阶段任务，返回下一个任务类型；None 表示流水线终止。"""
    source = session.get(KnowledgeSource, task.source_id)
    version = session.get(DocumentVersion, task.version_id)
    if source is None or version is None:
        raise PipelineError(
            "NOT_FOUND", "TASK_TARGET_MISSING", "任务指向的来源或版本不存在", retryable=False
        )

    version.processing_stage = STAGE_NAMES[task.task_type]
    logger.info("stage_start", extra={"stage": task.task_type})

    handlers = {
        "FETCH": _fetch,
        "PARSE": _mock_parse,
        "CLASSIFY": _mock_classify,
        "CHUNK": _mock_chunk,
        "EMBED": _mock_embed,
        "INDEX": _mock_index,
        "FINALIZE": _mock_finalize,
    }
    try:
        next_type = handlers[task.task_type](
            session, source, version, task,
            provider=provider, oauth_client=oauth_client, store=store,
        )
        logger.info("stage_done", extra={"stage": task.task_type, "next_stage": next_type})
        return next_type
    except FeishuError as exc:
        raise PipelineError(exc.category, exc.code, exc.message, retryable=exc.retryable) from exc


def _fetch(
    session: Session,
    source: KnowledgeSource,
    version: DocumentVersion,
    task,
    *,
    provider: FeishuDocumentProvider,
    oauth_client: FeishuOAuthClient,
    store,
) -> str | None:
    detail = session.get(FeishuSourceDetail, source.id)
    resource_token = detail.resource_token if detail else source.canonical_key
    resource_type = (detail.resource_type.casefold() if detail and detail.resource_type else "wiki")

    # user_access_token 由来源 owner 的飞书绑定解析（未绑定则 None，Fake 忽略、Real 需凭据）
    user_access_token = get_user_access_token(session, source.owner_user_id, oauth_client)
    content = provider.fetch_content(user_access_token, resource_token, resource_type)

    if version.external_revision and content.revision and version.external_revision != content.revision:
        return _bump_version(session, source, version, content)

    raw_key = f"raw/{source.id}/{version.id}/original.json"
    store.put(raw_key, json.dumps(content.raw_payload, ensure_ascii=False).encode("utf-8"))
    version.raw_object_key = raw_key
    version.external_revision = content.revision
    version.source_modified_at = content.modified_at
    version.content_sha256 = hashlib.sha256(content.text.encode("utf-8")).hexdigest()
    return NEXT_STAGE["FETCH"]


def _bump_version(
    session: Session, source: KnowledgeSource, version: DocumentVersion, content
) -> None:
    """文档已更新：终止当前版本，为最新 revision 创建新版本并从 FETCH 重跑（DD-04 §6.2）。"""
    new_version = DocumentVersion(
        source_id=source.id,
        version_no=version.version_no + 1,
        status="PROCESSING",
        processing_stage="FETCHING",
        external_revision=content.revision,
        source_modified_at=content.modified_at,
    )
    session.add(new_version)
    session.flush()
    source.pending_version_id = new_version.id

    version.status = "FAILED"
    version.error_code = "DOC_REVISION_CHANGED"
    version.error_summary = "获取到的版本与已记录版本不一致，已创建新版本重新处理"
    version.processing_stage = None

    session.add(
        ProcessingTask(
            task_type="FETCH",
            status="PENDING",
            idempotency_key=f"version:{new_version.id}:stage:fetch",
            scheduled_at=datetime.now(timezone.utc),
            source_id=source.id,
            version_id=new_version.id,
            payload={
                "source_id": str(source.id),
                "version_id": str(new_version.id),
                "reason": "DOC_UPDATED",
            },
            priority=100,
            max_attempts=3,
            created_by_user_id=source.owner_user_id,
        )
    )
    return None


def _mock_parse(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store,
) -> str | None:
    version.parsed_object_key = f"parsed/{source.id}/{version.id}/document-v1.json"
    version.parser_name = "mock-parser"
    version.parser_version = "1.0"
    return NEXT_STAGE["PARSE"]


def _mock_classify(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store,
) -> str | None:
    marker = source.canonical_key
    if "uncertain" in marker:
        version.status = "PENDING_CONFIRMATION"
        source.status = "PENDING_CONFIRMATION"
        return None
    if "irrelevant" in marker:
        version.status = "FAILED"
        version.error_code = "CLASSIFIED_IRRELEVANT"
        version.error_summary = "分类判定与平台知识无关，不入库"
        source.status = "OFFLINE"
        source.offline_reason = "明确无关"
        return None
    return NEXT_STAGE["CLASSIFY"]


def _mock_chunk(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store,
) -> str | None:
    # 真实切片会写入 document_chunks；mock 阶段只推进流水线
    return NEXT_STAGE["CHUNK"]


def _mock_embed(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store,
) -> str | None:
    version.embedding_model_key = "mock-embedding"
    version.embedding_dimension = 384
    return NEXT_STAGE["EMBED"]


def _mock_index(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store,
) -> str | None:
    version.index_generation = f"v{version.version_no}-1"
    return NEXT_STAGE["INDEX"]


def _mock_finalize(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store,
) -> str | None:
    """激活事务（DD-02 §7.3）：锁定来源，校验未下线，原子切换 current_version。"""
    locked_source = session.execute(
        select(KnowledgeSource).where(KnowledgeSource.id == source.id).with_for_update()
    ).scalar_one()
    if locked_source.status == "OFFLINE":
        raise PipelineError(
            "CONFLICT", "SOURCE_OFFLINE", "来源已下线，不激活版本", retryable=False
        )
    if locked_source.current_version_id and locked_source.current_version_id != version.id:
        old = session.get(DocumentVersion, locked_source.current_version_id)
        if old is not None:
            old.status = "SUPERSEDED"
    version.status = "READY"
    version.processing_stage = None
    locked_source.current_version_id = version.id
    locked_source.pending_version_id = None
    locked_source.status = "QUERYABLE"
    locked_source.update_status = "IDLE"
    return None
