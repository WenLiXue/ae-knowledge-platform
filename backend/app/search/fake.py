"""内存检索引擎适配器（DD-19 §11.2，仅开发/测试）。

按 doc_id 覆盖写入；delete_generation 按 generation 过滤删除。Phase 5 起提供
``search``（bm25：确定性 BM25；vector：余弦相似度），可按 version_id 预过滤。
供流水线集成测试与开发环境使用，生产切换 OpenSearchSearchAdapter。
"""

from __future__ import annotations

import math

from .base import BulkIndexResult, SearchResult
from .bm25 import score_documents


class FakeSearchAdapter:
    """确定性内存实现。同一实例保留全部写入，跨阶段共享（由 Worker 注入）。"""

    def __init__(self):
        self._docs: dict[str, dict] = {}
        self._by_generation: dict[str, set[str]] = {}
        # 测试注入：需要被判定为失败的 doc_id（bulk 时跳过并计入 failed）
        self.fail_bulk: set[str] = set()

    def bulk_index(self, docs: list[dict], *, generation: str) -> BulkIndexResult:
        failed: list[str] = []
        for doc in docs:
            did = doc.get("_id") or doc.get("doc_id")
            if not did:
                failed.append(str(doc.get("chunk_id", "?")))
                continue
            if did in self.fail_bulk:
                failed.append(did)
                continue
            self._docs[did] = dict(doc)
            self._by_generation.setdefault(generation, set()).add(did)
        return BulkIndexResult(indexed=len(docs) - len(failed), failed=failed)

    def delete_generation(self, generation: str) -> int:
        ids = self._by_generation.pop(generation, set())
        removed = 0
        for did in ids:
            if did in self._docs:
                del self._docs[did]
                removed += 1
        return removed

    def count_by_generation(self, generation: str) -> int:
        return len(self._by_generation.get(generation, set()))

    def get(self, doc_id: str) -> dict | None:
        return self._docs.get(doc_id)

    def sample(self, generation: str, limit: int = 3) -> list[dict]:
        ids = sorted(self._by_generation.get(generation, set()))[:limit]
        return [self._docs[i] for i in ids]

    def search(
        self,
        *,
        query_text: str | None = None,
        embedding: list[float] | None = None,
        retrieval_type: str,
        top_k: int,
        version_ids: list[str] | None = None,
    ) -> SearchResult:
        """确定性检索。bm25 用内部 BM25；vector 用余弦相似度；按 version_id 预过滤。"""
        docs = list(self._docs.values())
        if version_ids:
            allowed = set(version_ids)
            docs = [d for d in docs if d.get("version_id") in allowed]
        by_id = {d.get("_id") or d.get("doc_id"): d for d in docs}

        if retrieval_type == "bm25":
            if not query_text:
                return SearchResult(hits=[], total=0)
            corpus = [(did, _bm25_text(doc)) for did, doc in by_id.items()]
            ranked = score_documents(corpus, query_text)[:top_k]
            hits = []
            for did, score in ranked:
                doc = dict(by_id[did])
                doc["_score"] = score
                hits.append(doc)
            return SearchResult(hits=hits, total=len(ranked))

        if retrieval_type == "vector":
            if not embedding:
                return SearchResult(hits=[], total=0)
            scored: list[tuple[str, float]] = []
            for did, doc in by_id.items():
                sim = _cosine_similarity(embedding, doc.get("embedding"))
                if sim is not None:
                    scored.append((did, sim))
            scored.sort(key=lambda item: item[1], reverse=True)
            hits = []
            for did, score in scored[:top_k]:
                doc = dict(by_id[did])
                doc["_score"] = score
                hits.append(doc)
            return SearchResult(hits=hits, total=len(scored))

        raise ValueError(f"未知检索类型: {retrieval_type}")

    def health(self) -> bool:
        return True


def _bm25_text(doc: dict) -> str:
    parts = [doc.get("content") or ""]
    if doc.get("title"):
        parts.append(str(doc["title"]))
    heading = doc.get("heading_path") or []
    if heading:
        parts.append(" ".join(str(h) for h in heading))
    return " ".join(parts)


def _cosine_similarity(a: list[float] | None, b: object) -> float | None:
    if not a or not isinstance(b, list) or not b:
        return None
    if len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)
