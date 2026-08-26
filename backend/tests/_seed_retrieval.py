"""检索测试播种助手：目录/来源/版本/元数据/切片/索引。

只写数据库状态 + FakeSearchAdapter，不依赖 Worker；供 filters/service/eval 测试复用。
embedding 用确定性词袋哈希向量，保证共享 token 的文本余弦更高（可复现）。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.db.models.catalog import DocumentType, Product, ProductVersion, SourcePriority
from app.db.models.knowledge import DocumentVersion, KnowledgeSource
from app.db.models.rag import DocumentChunk, DocumentMetadata
from app.search.bm25 import tokenize
from app.search.fake import FakeSearchAdapter
from app.search.mapping import doc_id

SYSTEM_USER = "11111111-1111-1111-1111-111111111111"
EMBED_DIM = 8


@dataclass
class SeededDoc:
    source: KnowledgeSource
    version: DocumentVersion
    chunks: list[DocumentChunk]


def seed_catalog(db) -> dict:
    """产品 AE + 版本 V7.0 + product-spec/product-whitepaper + feishu 优先级 1。"""
    product = Product(code="AE", name="AE产品", sort_order=1)
    db.add(product)
    db.flush()
    pv = ProductVersion(product_id=product.id, version_code="V7.0", major_version=7, minor_version=0, sort_order=1)
    db.add(pv)
    spec = DocumentType(code="product-spec", name="产品规格", sort_order=10)
    wp = DocumentType(code="product-whitepaper", name="产品白皮书", sort_order=20)
    db.add_all([spec, wp])
    db.add(SourcePriority(source_code="feishu", display_name="飞书", priority=1))
    db.flush()
    return {"product": product, "product_version": pv, "spec": spec, "wp": wp}


def make_embedding(text: str, dim: int = EMBED_DIM) -> list[float]:
    """确定性词袋哈希向量：共享 token 的文本余弦更高。"""
    vec = [0.0] * dim
    for token in tokenize(text):
        idx = hashlib.sha256(token.encode("utf-8")).digest()[0] % dim
        vec[idx] += 1.0
    return vec


def add_document(
    db,
    adapter: FakeSearchAdapter,
    *,
    display_name: str,
    doc_type: DocumentType,
    product: Product,
    product_version: ProductVersion,
    chunks: list[str],
    status_source: str = "QUERYABLE",
    status_version: str = "READY",
    source_priority: int = 1,
    canonical_key: str | None = None,
) -> SeededDoc:
    """建一个来源 + 版本 + 元数据 + 切片，并把切片索引进 adapter（按版本 generation）。"""
    source = KnowledgeSource(
        owner_user_id=uuid.UUID(SYSTEM_USER),
        source_type="feishu",
        canonical_key=canonical_key or f"key-{uuid.uuid4().hex[:16]}",
        display_name=display_name,
        status=status_source,
    )
    db.add(source)
    db.flush()
    generation = f"gen-{uuid.uuid4().hex[:12]}"
    version = DocumentVersion(
        source_id=source.id,
        version_no=1,
        status=status_version,
        source_modified_at=datetime.now(timezone.utc),
        index_generation=generation,
    )
    db.add(version)
    db.flush()
    source.current_version_id = version.id
    db.add(
        DocumentMetadata(
            version_id=version.id,
            product_id=product.id,
            product_version_id=product_version.id,
            document_type_id=doc_type.id,
        )
    )
    rows: list[DocumentChunk] = []
    for i, text in enumerate(chunks, start=1):
        chunk = DocumentChunk(
            version_id=version.id,
            ordinal=i,
            chunk_type="paragraph",
            content=text,
            content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            heading_path=[display_name],
            locator_json={"element_ids": [f"el-{i:04d}"]},
            metadata_snapshot={
                "product_code": product.code,
                "product_version_code": product_version.version_code,
                "document_type_code": doc_type.code,
            },
            token_count=max(1, len(text) // 3),
        )
        db.add(chunk)
        db.flush()
        rows.append(chunk)
    db.flush()
    adapter.bulk_index(
        [
            build_index_doc(source, version, chunk, product, product_version, doc_type, source_priority)
            for chunk in rows
        ],
        generation=generation,
    )
    return SeededDoc(source=source, version=version, chunks=rows)


def make_user(s, *, is_admin: bool = False, display_name: str = "普通用户"):
    """建一个系统用户（conftest 已播种 system 用户，本函数建业务用户）。"""
    from app.db.models.user import User

    user = User(display_name=display_name, status="ACTIVE", is_admin=is_admin, created_source="ADMIN")
    s.add(user)
    s.flush()
    return user


def user_cookies(s, user) -> dict:
    """为指定用户建立会话 Cookie（供 TestClient 认证）。"""
    from app.auth import sessions
    from app.core.config import get_settings

    token = sessions.create_session(s, user.id, 24)
    s.commit()
    return {get_settings().session_cookie_name: token}


def fake_retrieval_service(adapter: FakeSearchAdapter):
    """假检索服务：确定性 embed/rerank（共享 token 的余弦）。"""
    from app.retrieval.service import EmbedOutcome, RetrievalService, RerankOutcome

    def embed(db, query):
        return EmbedOutcome(embedding=make_embedding(query), model_key="fake-embed")

    def rerank(db, query, documents, top_n):
        qv = make_embedding(query)
        scored = []
        for i, doc in enumerate(documents):
            dv = make_embedding(doc)
            dot = sum(a * b for a, b in zip(qv, dv))
            na = (sum(a * a for a in qv)) ** 0.5
            nb = (sum(a * a for a in dv)) ** 0.5
            scored.append((i, dot / (na * nb) if na and nb else 0.0))
        scored.sort(key=lambda item: item[1], reverse=True)
        return RerankOutcome(results=scored[:top_n], model_key="fake-rerank")

    return RetrievalService(search=adapter, embed_fn=embed, rerank_fn=rerank)


def run_answer_task(adapter, *, answer_id=None, chat_fn=None, settings=None):
    """查找（最旧未执行）answer 的 GENERATE_ANSWER 任务并执行。

    feature_real_qa 默认关闭 → 确定性 mock 生成；内部自开会话（worker 会多次 commit）。
    """
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.db.models.task import ProcessingTask
    from app.qa.worker import run_generate_answer

    with SessionLocal() as s:
        query = select(ProcessingTask).where(ProcessingTask.task_type == "GENERATE_ANSWER")
        if answer_id:
            query = query.where(ProcessingTask.payload["answer_id"].astext == str(answer_id))
        task = s.execute(
            query.order_by(ProcessingTask.created_at.desc()).limit(1)
        ).scalars().first()
        assert task is not None, "未找到 GENERATE_ANSWER 任务"
        svc = fake_retrieval_service(adapter)
        return run_generate_answer(
            s, task, search=adapter, retrieval_service=svc, chat_fn=chat_fn, settings=settings
        )


def build_index_doc(
    source,
    version,
    chunk,
    product,
    product_version,
    doc_type,
    source_priority: int,
) -> dict:
    did = doc_id(str(chunk.id), version.index_generation)
    return {
        "_id": did,
        "doc_id": did,
        "chunk_id": str(chunk.id),
        "generation": version.index_generation,
        "source_id": str(source.id),
        "version_id": str(version.id),
        "title": source.display_name,
        "content": chunk.content,
        "content_sha256": chunk.content_sha256,
        "heading_path": chunk.heading_path or [],
        "locator": chunk.locator_json or {},
        "chunk_type": chunk.chunk_type,
        "ordinal": chunk.ordinal,
        "embedding": make_embedding(chunk.content),
        "product_code": product.code,
        "product_version_code": product_version.version_code,
        "document_type_code": doc_type.code,
        "product_form_code": None,
        "source_modified_at": version.source_modified_at.isoformat() if version.source_modified_at else None,
        "source_priority": source_priority,
        "token_count": chunk.token_count,
    }
