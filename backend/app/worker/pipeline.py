"""文档处理流水线。

阶段顺序对齐 DD-04 §5：FETCH → PARSE → CLASSIFY → CHUNK → EMBED → INDEX → FINALIZE。

- FETCH 通过 FeishuDocumentProvider 读取真实/模拟正文，raw 内容写入对象存储（本地实现），
  并记录 revision / modified_at；获取到的 revision 与已记录版本不一致时终止当前版本、
  创建新版本重新处理（DD-04 §6.2）。
- PARSE 读取 raw 对象，用真实解析器产出版本化 ParsedDocument（DD-19 §6），
  先写临时 key 再原子发布固定 key，重复执行覆盖同一版本产物。
- CLASSIFY 在 feature_real_classification=True 时走真实分类（DD-19 §8）：
  读 ParsedDocument → 模型分类 → 写 classification_results / document_metadata，
  RELEVANT 进 CHUNK、UNCERTAIN 置 PENDING_CONFIRMATION、IRRELEVANT 来源 OFFLINE；
  Flag 关闭时保持确定性 mock（token 含 uncertain/irrelevant 判定）。
- CHUNK/EMBED/INDEX/FINALIZE 在 feature_real_indexing=True 时走真实实现（DD-19 §10-§11）：
  CHUNK 写 document_chunks（替换式幂等）、EMBED 分批向量化并严格校验（失败不进 INDEX）、
  INDEX 写隔离 generation 并 VERIFY（数量/抽样/metadata）、FINALIZE 原子切换 current_version
  并为旧 generation 创建异步 CLEANUP 任务；只有 VERIFY 通过才进入 QUERYABLE。
  Flag 关闭时保持原 mock 阶段。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..auth.feishu import get_user_access_token
from ..chunking import chunk_document, load_chunking_config
from ..classify import service as classify_service
from ..classify.service import ClassificationError
from ..core.config import get_settings
from ..db.models.catalog import DocumentType, Product, ProductForm, ProductVersion, SourcePriority
from ..db.models.knowledge import DocumentVersion, FeishuSourceDetail, KnowledgeSource
from ..db.models.rag import DocumentChunk, DocumentMetadata
from ..db.models.task import ProcessingTask
from ..embedding import EmbeddingError, embed_chunks
from ..feishu_auth.base import FeishuOAuthClient
from ..feishu_provider.base import FeishuError, FeishuDocumentProvider
from ..llm.runtime import resolve_service_model
from ..llm.service import LLMConfigError
from ..model_gateway import create_gateway
from ..model_gateway.errors import GatewayError
from ..parsing import ParsedDocument, parse_feishu_payload
from ..search import SearchAdapterError, doc_id

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
    "CLEANUP": "CLEANING",
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
    search=None,
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
        "PARSE": _parse,
        "CLASSIFY": _classify,
        "CHUNK": _chunk,
        "EMBED": _embed,
        "INDEX": _index,
        "FINALIZE": _finalize,
        "CLEANUP": _cleanup,
    }
    try:
        next_type = handlers[task.task_type](
            session, source, version, task,
            provider=provider, oauth_client=oauth_client, store=store, search=search,
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
    search=None,
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


def _parse(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store, search=None,
) -> str | None:
    """真实解析：读取 raw 对象 → ParsedDocument → 原子发布 parsed 对象（DD-19 §6.2）。

    - 相同输入重复执行覆盖同一版本产物，不追加；
    - 先写临时 key，再原子发布固定 key（对象存储接入后固定 key 写入为原子操作）。
    """
    if not version.raw_object_key or not store.exists(version.raw_object_key):
        raise PipelineError("VALIDATION", "RAW_MISSING", "缺少 raw 对象，无法解析", retryable=False)
    raw = json.loads(store.get(version.raw_object_key).decode("utf-8"))
    parsed = parse_feishu_payload(raw, title=source.display_name, source_type=source.source_type)
    final_key = f"parsed/{source.id}/{version.id}/document-v1.json"
    tmp_key = f"{final_key}.tmp"
    data = parsed.model_dump_json(indent=2).encode("utf-8")
    store.put(tmp_key, data)
    store.put(final_key, data)
    version.parsed_object_key = final_key
    version.parser_name = "feishu-parse"
    version.parser_version = "1.0"
    logger.info("parse_done", extra={"stage": "PARSE", "element_count": parsed.stats.get("element_count", 0)})
    return NEXT_STAGE["PARSE"]


def _classify(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store, search=None,
) -> str | None:
    """分类阶段入口：feature_real_classification 开启时走真实分类，否则保持 mock。"""
    if get_settings().feature_real_classification:
        return _real_classify(
            session, source, version, task, provider=provider, oauth_client=oauth_client, store=store
        )
    return _mock_classify(
        session, source, version, task, provider=provider, oauth_client=oauth_client, store=store
    )


def _real_classify(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store, search=None,
) -> str | None:
    """真实分类（DD-19 §8、§8.5）。

    模型调用发生在事务外：读取配置与已存在 input_hash 在短事务内完成并提交释放锁，
    之后调用模型，最后短事务锁定版本应用结果。模型不可用（未配置/网络错误）一律
    不允许默认相关：配置缺失立即失败，可重试错误进入任务重试。
    """
    if not version.parsed_object_key or not store.exists(version.parsed_object_key):
        raise PipelineError("VALIDATION", "PARSED_MISSING", "缺少 parsed 对象，无法分类", retryable=False)
    parsed_data = json.loads(store.get(version.parsed_object_key).decode("utf-8"))
    parsed = ParsedDocument.model_validate(parsed_data)

    try:
        resolved = resolve_service_model(session, "DOCUMENT_CLASSIFICATION")
        gateway = create_gateway(resolved)
        result = classify_service.run_classification(
            session,
            version_id=version.id,
            source_id=source.id,
            parsed=parsed,
            gateway=gateway,
            resolved=resolved,
        )
    except LLMConfigError as exc:
        raise PipelineError("CONFIG", exc.code, exc.message, retryable=False) from exc
    except ClassificationError as exc:
        raise PipelineError(exc.category, exc.code, exc.message, retryable=exc.retryable) from exc
    except GatewayError as exc:
        # create_gateway 的 CONFIG 类错误（不支持的服务商/缺 Key）在此统一转为
        # 非重试的明确失败，而不是当作 INTERNAL 重试（DD-19 §16）。
        raise PipelineError(exc.category, exc.code, exc.message, retryable=exc.retryable) from exc
    # 分类结果在独立短会话中已提交；让外层会话从 DB 重读版本/来源状态，
    # 避免 execute_stage 设置的 processing_stage 覆盖已提交的分类结果（§8.5）。
    session.expire_all()
    return result.next_stage


def _mock_classify(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store, search=None,
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


def _chunk(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store, search=None,
) -> str | None:
    """切片阶段入口：feature_real_indexing 开启走真实切片，否则保持 mock。"""
    if get_settings().feature_real_indexing:
        return _real_chunk(session, source, version, task, store=store)
    return _mock_chunk(
        session, source, version, task, provider=provider, oauth_client=oauth_client, store=store
    )


def _embed(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store, search=None,
) -> str | None:
    if get_settings().feature_real_indexing:
        return _real_embed(session, source, version, task, store=store)
    return _mock_embed(
        session, source, version, task, provider=provider, oauth_client=oauth_client, store=store
    )


def _index(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store, search=None,
) -> str | None:
    if get_settings().feature_real_indexing:
        return _real_index(session, source, version, task, store=store, search=search)
    return _mock_index(
        session, source, version, task, provider=provider, oauth_client=oauth_client, store=store
    )


def _finalize(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store, search=None,
) -> str | None:
    if get_settings().feature_real_indexing:
        return _real_finalize(session, source, version, task, search=search)
    return _mock_finalize(
        session, source, version, task, provider=provider, oauth_client=oauth_client, store=store
    )


def _mock_chunk(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store, search=None,
) -> str | None:
    # 真实切片会写入 document_chunks；mock 阶段只推进流水线
    return NEXT_STAGE["CHUNK"]


def _mock_embed(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store, search=None,
) -> str | None:
    version.embedding_model_key = "mock-embedding"
    version.embedding_dimension = 384
    return NEXT_STAGE["EMBED"]


def _mock_index(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store, search=None,
) -> str | None:
    version.index_generation = f"v{version.version_no}-1"
    return NEXT_STAGE["INDEX"]


def _mock_finalize(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store, search=None,
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


def _real_chunk(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    store,
) -> str | None:
    """真实切片（DD-19 §10）：读 ParsedDocument → chunk_document → 替换式写入 document_chunks。"""
    if not version.parsed_object_key or not store.exists(version.parsed_object_key):
        raise PipelineError("VALIDATION", "PARSED_MISSING", "缺少 parsed 对象，无法切片", retryable=False)
    parsed_data = json.loads(store.get(version.parsed_object_key).decode("utf-8"))
    parsed = ParsedDocument.model_validate(parsed_data)
    config = load_chunking_config(session)
    snapshot = _build_metadata_snapshot(session, source, version)
    specs = chunk_document(parsed, metadata_snapshot=snapshot, config=config)
    if not specs:
        raise PipelineError("VALIDATION", "NO_CHUNKS", "文档没有可切片内容", retryable=False)
    # 幂等：同一版本替换式写入（不追加），唯一 (version_id, ordinal) 兜底
    session.execute(delete(DocumentChunk).where(DocumentChunk.version_id == version.id))
    for i, spec in enumerate(specs, start=1):
        session.add(
            DocumentChunk(
                version_id=version.id,
                ordinal=i,
                chunk_type=spec.chunk_type,
                content=spec.content,
                content_sha256=spec.content_sha256,
                heading_path=spec.heading_path,
                locator_json=spec.locator,
                metadata_snapshot=spec.metadata_snapshot,
                token_count=spec.token_count,
                embedding_status="PENDING",
            )
        )
    logger.info("chunk_done", extra={"stage": "CHUNK", "chunk_count": len(specs)})
    return NEXT_STAGE["CHUNK"]


def _real_embed(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    store,
) -> str | None:
    """真实向量化（DD-19 §11.1）：分批调用模型 → 校验 → 写 derived 向量对象（不落 PostgreSQL）。"""
    chunks = session.execute(
        select(DocumentChunk)
        .where(DocumentChunk.version_id == version.id)
        .order_by(DocumentChunk.ordinal)
    ).scalars().all()
    if not chunks:
        raise PipelineError("VALIDATION", "NO_CHUNKS", "版本没有切片，无法向量化", retryable=False)
    try:
        resolved = resolve_service_model(session, "DOCUMENT_EMBEDDING")
    except LLMConfigError as exc:
        raise PipelineError("CONFIG", exc.code, exc.message, retryable=False) from exc
    gateway = create_gateway(resolved)
    try:
        result = embed_chunks(
            chunks,
            gateway=gateway,
            model_name=resolved.model_name,
            batch_size=get_settings().embedding_batch_size,
        )
    except EmbeddingError as exc:
        raise PipelineError(exc.category, exc.code, exc.message, retryable=exc.retryable) from exc
    except GatewayError as exc:
        raise PipelineError(exc.category, exc.code, exc.message, retryable=exc.retryable) from exc

    by_id = {it.chunk_id: it for it in result.items}
    items = []
    for chunk in chunks:
        it = by_id[chunk.id]
        items.append(
            {
                "chunk_id": str(it.chunk_id),
                "ordinal": chunk.ordinal,
                "content": it.content,
                "content_sha256": chunk.content_sha256,
                "heading_path": chunk.heading_path or [],
                "locator": chunk.locator_json or {},
                "metadata_snapshot": chunk.metadata_snapshot or {},
                "embedding": it.embedding,
                "chunk_type": chunk.chunk_type,
            }
        )
    key = f"derived/{source.id}/{version.id}/embeddings-v1.json"
    store.put(
        key,
        json.dumps(
            {
                "model_key": resolved.model_config_id,
                "model_revision": str(resolved.config_revision) if resolved.config_revision is not None else None,
                "dimension": result.dimension,
                "items": items,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
    )
    version.embedding_model_key = resolved.model_config_id
    version.embedding_dimension = result.dimension
    session.execute(
        update(DocumentChunk).where(DocumentChunk.version_id == version.id).values(embedding_status="EMBEDDED")
    )
    logger.info("embed_done", extra={"stage": "EMBED", "chunk_count": len(items), "dimension": result.dimension})
    return NEXT_STAGE["EMBED"]


def _real_index(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    store, search=None,
) -> str | None:
    """真实索引 + VERIFY（DD-19 §11.2/§11.3）：写隔离 generation → 校验通过才返回 FINALIZE。"""
    if search is None:
        raise PipelineError("CONFIG", "SEARCH_ADAPTER_MISSING", "检索引擎适配器未注入", retryable=False)
    key = f"derived/{source.id}/{version.id}/embeddings-v1.json"
    if not store.exists(key):
        raise PipelineError("VALIDATION", "EMBEDDINGS_MISSING", "缺少向量产物，无法索引", retryable=False)
    data = json.loads(store.get(key).decode("utf-8"))
    generation = f"gen-{version.id}"
    docs = [_build_index_doc(source, version, item, generation) for item in data["items"]]
    try:
        result = search.bulk_index(docs, generation=generation)
        if result.failed:
            raise PipelineError(
                "PROVIDER", "INDEX_PARTIAL_FAILURE", f"索引部分失败: {len(result.failed)} 项", retryable=True
            )
        _verify_index(session, source, version, search, generation, docs)
    except SearchAdapterError as exc:
        raise PipelineError(exc.category, exc.code, exc.message, retryable=exc.retryable) from exc
    version.index_generation = generation
    logger.info("index_done", extra={"stage": "INDEX", "generation": generation, "indexed": result.indexed})
    return NEXT_STAGE["INDEX"]


def _verify_index(session, source, version, search, generation, docs) -> None:
    """VERIFY（DD-19 §11.3）：DB Chunk 数 = 索引成功数；抽样可读；generation 可过滤；metadata 一致。"""
    db_count = session.execute(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.version_id == version.id)
    ).scalar_one()
    idx_count = search.count_by_generation(generation)
    if db_count != len(docs) or idx_count != db_count:
        raise PipelineError(
            "PROVIDER",
            "INDEX_VERIFY_COUNT",
            f"索引数量校验失败: DB={db_count} 写入={len(docs)} 索引={idx_count}",
            retryable=True,
        )
    samples = search.sample(generation, limit=3)
    if db_count > 0 and not samples:
        raise PipelineError("PROVIDER", "INDEX_VERIFY_SAMPLE", "无法按 generation 抽样读取", retryable=True)
    for doc in samples:
        if doc.get("version_id") != str(version.id) or doc.get("generation") != generation:
            raise PipelineError("PROVIDER", "INDEX_VERIFY_METADATA", "索引文档元数据与版本不一致", retryable=True)


def _build_index_doc(source, version, item, generation) -> dict:
    """构造索引文档（字段对齐 mapping.py）。"""
    snapshot = item.get("metadata_snapshot") or {}
    chunk_id = item["chunk_id"]
    return {
        "_id": doc_id(chunk_id, generation),
        "doc_id": doc_id(chunk_id, generation),
        "chunk_id": chunk_id,
        "generation": generation,
        "source_id": str(source.id),
        "version_id": str(version.id),
        "title": snapshot.get("title") or source.display_name,
        "content": item.get("content", ""),
        "content_sha256": item.get("content_sha256"),
        "heading_path": item.get("heading_path") or [],
        "locator": item.get("locator") or {},
        "chunk_type": item.get("chunk_type"),
        "ordinal": item.get("ordinal"),
        "embedding": item.get("embedding") or [],
        "product_code": snapshot.get("product_code"),
        "product_version_code": snapshot.get("product_version_code"),
        "document_type_code": snapshot.get("document_type_code"),
        "product_form_code": snapshot.get("product_form_code"),
        "source_modified_at": snapshot.get("source_modified_at"),
        "source_priority": snapshot.get("source_priority", 0),
    }


def _build_metadata_snapshot(session, source, version) -> dict:
    """把版本元数据解析为索引快照（FK → code，写入 Chunk metadata_snapshot 供索引过滤/展示）。"""
    meta = session.get(DocumentMetadata, version.id)
    snapshot = {
        "source_id": str(source.id),
        "version_id": str(version.id),
        "title": source.display_name,
        "source_type": source.source_type,
        "source_modified_at": version.source_modified_at.isoformat() if version.source_modified_at else None,
        "product_code": None,
        "product_version_code": None,
        "document_type_code": None,
        "product_form_code": None,
        "source_priority": 0,
    }
    if meta is not None:
        if meta.product_id:
            row = session.get(Product, meta.product_id)
            snapshot["product_code"] = row.code if row else None
        if meta.product_version_id:
            row = session.get(ProductVersion, meta.product_version_id)
            snapshot["product_version_code"] = row.version_code if row else None
        if meta.document_type_id:
            row = session.get(DocumentType, meta.document_type_id)
            snapshot["document_type_code"] = row.code if row else None
        if meta.product_form_id:
            row = session.get(ProductForm, meta.product_form_id)
            snapshot["product_form_code"] = row.code if row else None
    priority = session.execute(
        select(SourcePriority)
        .where(SourcePriority.source_code == source.source_type, SourcePriority.status == "ENABLED")
        .order_by(SourcePriority.priority)
    ).scalars().first()
    if priority is not None:
        snapshot["source_priority"] = priority.priority
    return snapshot


def _real_finalize(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    search=None,
) -> str | None:
    """真实激活事务（DD-04 §6.8）：锁定来源、校验未下线、原子切换 current_version、
    旧 generation 异步清理。来源已下线时不激活并安排当前 generation 清理。"""
    locked_source = session.execute(
        select(KnowledgeSource).where(KnowledgeSource.id == source.id).with_for_update()
    ).scalar_one()
    if locked_source.status == "OFFLINE":
        if version.index_generation:
            _create_cleanup_task(session, locked_source, version, version.index_generation)
        raise PipelineError("CONFLICT", "SOURCE_OFFLINE", "来源已下线，不激活版本", retryable=False)
    old_version = None
    if locked_source.current_version_id and locked_source.current_version_id != version.id:
        old_version = session.get(DocumentVersion, locked_source.current_version_id)
        if old_version is not None:
            old_version.status = "SUPERSEDED"
    version.status = "READY"
    version.processing_stage = None
    locked_source.current_version_id = version.id
    locked_source.pending_version_id = None
    locked_source.status = "QUERYABLE"
    locked_source.update_status = "IDLE"
    # 旧 generation 异步清理（清理失败不回滚已激活版本，由 CLEANUP 任务失败告警）
    if old_version is not None and old_version.index_generation:
        _create_cleanup_task(session, locked_source, old_version, old_version.index_generation)
    return None


def _create_cleanup_task(session, source, version, generation) -> None:
    """创建旧 generation 异步清理任务（幂等键含 generation，重复创建被唯一索引拦截）。"""
    key = f"version:{version.id}:stage:cleanup:{generation}"
    existing = session.execute(
        select(ProcessingTask).where(
            ProcessingTask.idempotency_key == key,
            ProcessingTask.status.in_(("PENDING", "RUNNING", "RETRY_WAIT")),
        )
    ).scalars().first()
    if existing is not None:
        return
    session.add(
        ProcessingTask(
            task_type="CLEANUP",
            status="PENDING",
            idempotency_key=key,
            scheduled_at=datetime.now(timezone.utc),
            source_id=source.id,
            version_id=version.id,
            payload={"index_generation": generation, "reason": "GENERATION_SUPERSEDED"},
            priority=200,
            max_attempts=3,
            created_by_user_id=source.owner_user_id,
        )
    )


def _cleanup(
    session: Session, source: KnowledgeSource, version: DocumentVersion, task, *,
    provider, oauth_client, store, search=None,
) -> str | None:
    """清理旧 generation（DD-04 §6.8）：删除索引中该 generation 的全部文档，幂等。"""
    if search is None:
        raise PipelineError("CONFIG", "SEARCH_ADAPTER_MISSING", "检索引擎适配器未注入", retryable=False)
    generation = (task.payload or {}).get("index_generation")
    if not generation:
        raise PipelineError("VALIDATION", "GENERATION_MISSING", "清理任务缺少代次", retryable=False)
    try:
        deleted = search.delete_generation(generation)
    except SearchAdapterError as exc:
        raise PipelineError(exc.category, exc.code, exc.message, retryable=exc.retryable) from exc
    logger.info("cleanup_done", extra={"stage": "CLEANUP", "generation": generation, "deleted": deleted})
    return None
