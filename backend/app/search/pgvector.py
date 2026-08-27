"""PostgreSQL + pgvector 检索适配器。

检索文档和向量与业务库同库持久化：PostgreSQL 全文检索负责 BM25 近似排序，
pgvector cosine distance 负责向量召回。保留 SearchAdapter 契约，便于测试和后续替换。
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from ..db.models.rag import VectorDocument
from ..db.session import SessionLocal
from .base import BulkIndexResult, SearchAdapterError, SearchResult


class PgVectorSearchAdapter:
    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory

    @staticmethod
    def _error(exc: Exception) -> SearchAdapterError:
        return SearchAdapterError(
            "PROVIDER", "SEARCH_DATABASE_ERROR", "PostgreSQL/pgvector 检索失败", retryable=True
        )

    @staticmethod
    def _row_to_doc(row: VectorDocument, score: float | None = None) -> dict:
        snapshot = dict(row.metadata_snapshot or {})
        doc = {
            "_id": row.doc_id,
            "doc_id": row.doc_id,
            "chunk_id": str(row.chunk_id),
            "generation": row.generation,
            "version_id": str(row.version_id),
            "title": row.title,
            "content": row.content,
            "content_sha256": row.content_sha256,
            "heading_path": row.heading_path or [],
            "locator": row.locator or {},
            "chunk_type": row.chunk_type,
            "ordinal": row.ordinal,
            **snapshot,
        }
        if score is not None:
            doc["_score"] = float(score)
        return doc

    def bulk_index(self, docs: list[dict], *, generation: str) -> BulkIndexResult:
        failed: list[str] = []
        try:
            with self.session_factory() as session:
                for doc in docs:
                    doc_id = str(doc.get("_id") or doc.get("doc_id") or "")
                    if not doc_id or not doc.get("embedding"):
                        failed.append(doc_id or str(doc.get("chunk_id", "?")))
                        continue
                    existing = session.get(VectorDocument, doc_id)
                    snapshot = {
                        key: doc.get(key)
                        for key in (
                            "source_id", "product_code", "product_version_code",
                            "document_type_code", "product_form_code",
                            "source_modified_at", "source_priority",
                        )
                        if doc.get(key) is not None
                    }
                    values = dict(
                        doc_id=doc_id,
                        chunk_id=uuid.UUID(str(doc["chunk_id"])),
                        version_id=uuid.UUID(str(doc["version_id"])),
                        generation=generation,
                        title=doc.get("title"),
                        content=doc.get("content", ""),
                        content_sha256=doc.get("content_sha256"),
                        heading_path=doc.get("heading_path") or [],
                        locator=doc.get("locator") or {},
                        chunk_type=doc.get("chunk_type"),
                        ordinal=doc.get("ordinal"),
                        metadata_snapshot=snapshot,
                        embedding=doc["embedding"],
                    )
                    if existing is None:
                        session.add(VectorDocument(**values))
                    else:
                        for key, value in values.items():
                            setattr(existing, key, value)
                session.commit()
        except (ValueError, SQLAlchemyError) as exc:
            raise self._error(exc) from exc
        return BulkIndexResult(indexed=len(docs) - len(failed), failed=failed)

    def delete_generation(self, generation: str) -> int:
        try:
            with self.session_factory() as session:
                result = session.execute(delete(VectorDocument).where(VectorDocument.generation == generation))
                session.commit()
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise self._error(exc) from exc

    def count_by_generation(self, generation: str) -> int:
        try:
            with self.session_factory() as session:
                return int(session.scalar(select(func.count()).select_from(VectorDocument).where(VectorDocument.generation == generation)) or 0)
        except SQLAlchemyError as exc:
            raise self._error(exc) from exc

    def get(self, doc_id: str) -> dict | None:
        try:
            with self.session_factory() as session:
                row = session.get(VectorDocument, doc_id)
                return self._row_to_doc(row) if row else None
        except SQLAlchemyError as exc:
            raise self._error(exc) from exc

    def sample(self, generation: str, limit: int = 3) -> list[dict]:
        try:
            with self.session_factory() as session:
                rows = session.scalars(
                    select(VectorDocument).where(VectorDocument.generation == generation).limit(limit)
                ).all()
                return [self._row_to_doc(row) for row in rows]
        except SQLAlchemyError as exc:
            raise self._error(exc) from exc

    def search(
        self,
        *,
        query_text: str | None = None,
        embedding: list[float] | None = None,
        retrieval_type: str,
        top_k: int,
        version_ids: list[str] | None = None,
    ) -> SearchResult:
        if retrieval_type == "bm25" and not query_text:
            return SearchResult(hits=[], total=0)
        if retrieval_type == "vector" and not embedding:
            return SearchResult(hits=[], total=0)
        try:
            with self.session_factory() as session:
                conditions = []
                if version_ids:
                    conditions.append(VectorDocument.version_id.in_([uuid.UUID(v) for v in version_ids]))
                if retrieval_type == "bm25":
                    document = func.to_tsvector(
                        "simple", func.concat(VectorDocument.title, " ", VectorDocument.content)
                    )
                    query = func.plainto_tsquery("simple", query_text)
                    score = func.ts_rank_cd(document, query).label("score")
                    statement = select(VectorDocument, score).where(*conditions, document.op("@@")(query)).order_by(score.desc()).limit(top_k)
                else:
                    distance = VectorDocument.embedding.cosine_distance(embedding).label("distance")
                    statement = select(VectorDocument, distance).where(*conditions).where(VectorDocument.embedding.is_not(None)).order_by(distance.asc()).limit(top_k)
                rows = session.execute(statement).all()
                hits = [
                    self._row_to_doc(row, 1.0 - float(score) if retrieval_type == "vector" else float(score))
                    for row, score in rows
                ]
                return SearchResult(hits=hits, total=len(hits))
        except (ValueError, SQLAlchemyError) as exc:
            raise self._error(exc) from exc

    def health(self) -> bool:
        try:
            with self.session_factory() as session:
                session.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False
