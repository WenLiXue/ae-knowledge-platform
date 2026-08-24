"""Mock 文档处理流水线。

在真实飞书 API / LLM 分类器 / 向量库接入前，用确定性 mock 推进各处理阶段，
使任务 Worker 与状态机可端到端测试、可演示。阶段顺序对齐 DD-04 §5：

    FETCH → PARSE → CLASSIFY → CHUNK → EMBED → INDEX → FINALIZE

失败与分类结果通过来源 canonical_key 中的标记注入，保证测试确定性：

- fail-once  ：FETCH 首次尝试可重试失败，第二次成功（验证重试恢复）
- transient  ：FETCH 持续可重试失败（验证重试耗尽 → FAILED）
- permanent  ：FETCH 不可重试失败（验证立即 FAILED）
- uncertain  ：CLASSIFY 判定 UNCERTAIN → 来源/版本进入 PENDING_CONFIRMATION
- irrelevant ：CLASSIFY 判定 IRRELEVANT → 来源 OFFLINE（明确无关）

其余 token 正常走完全流程并激活。真实实现接入后，用相同阶段契约替换各 handler。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.knowledge import DocumentVersion, KnowledgeSource

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


def execute_stage(session: Session, task) -> str | None:
    """执行一个阶段任务，返回下一个任务类型；None 表示流水线终止（正常或分类决定）。"""
    source = session.get(KnowledgeSource, task.source_id)
    version = session.get(DocumentVersion, task.version_id)
    if source is None or version is None:
        raise PipelineError(
            "NOT_FOUND", "TASK_TARGET_MISSING", "任务指向的来源或版本不存在", retryable=False
        )

    version.processing_stage = STAGE_NAMES[task.task_type]

    handlers = {
        "FETCH": _mock_fetch,
        "PARSE": _mock_parse,
        "CLASSIFY": _mock_classify,
        "CHUNK": _mock_chunk,
        "EMBED": _mock_embed,
        "INDEX": _mock_index,
        "FINALIZE": _mock_finalize,
    }
    return handlers[task.task_type](session, source, version, task)


def _inject_failure(source: KnowledgeSource, task) -> None:
    marker = source.canonical_key
    if "fail-once" in marker and task.attempt_count == 1:
        raise PipelineError("TRANSIENT", "MOCK_TRANSIENT", "模拟首次尝试失败，可重试", retryable=True)
    if "transient" in marker:
        raise PipelineError("TRANSIENT", "MOCK_TRANSIENT", "模拟持续可重试失败", retryable=True)
    if "permanent" in marker:
        raise PipelineError("VALIDATION", "MOCK_PERMANENT", "模拟不可重试失败", retryable=False)


def _mock_fetch(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task
) -> str | None:
    _inject_failure(source, task)
    version.raw_object_key = f"raw/{source.id}/{version.id}/original.mock"
    version.external_revision = "mock-rev-1"
    version.source_modified_at = datetime.now(timezone.utc)
    version.content_sha256 = hashlib.sha256(b"mock-content").hexdigest()
    return NEXT_STAGE["FETCH"]


def _mock_parse(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task
) -> str | None:
    version.parsed_object_key = f"parsed/{source.id}/{version.id}/document-v1.json"
    version.parser_name = "mock-parser"
    version.parser_version = "1.0"
    return NEXT_STAGE["PARSE"]


def _mock_classify(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task
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
    session: Session, source: KnowledgeSource, version: DocumentVersion, task
) -> str | None:
    # 真实切片会写入 document_chunks；mock 阶段只推进流水线
    return NEXT_STAGE["CHUNK"]


def _mock_embed(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task
) -> str | None:
    version.embedding_model_key = "mock-embedding"
    version.embedding_dimension = 384
    return NEXT_STAGE["EMBED"]


def _mock_index(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task
) -> str | None:
    version.index_generation = f"v{version.version_no}-1"
    return NEXT_STAGE["INDEX"]


def _mock_finalize(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task
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
