"""内存检索引擎适配器（DD-19 §11.2，仅开发/测试）。

按 doc_id 覆盖写入；delete_generation 按 generation 过滤删除。供流水线集成测试
与开发环境使用，生产切换 OpenSearchSearchAdapter。
"""

from __future__ import annotations

from .base import BulkIndexResult


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

    def health(self) -> bool:
        return True
