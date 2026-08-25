"""检索引擎适配器契约（DD-19 §11.2）。

- bulk_index：批量写入隔离 generation（索引文档 ID `chunk:{chunk_id}:generation:{generation}`）；
- delete_generation / count_by_generation / get / sample：供 VERIFY 与异步清理使用；
- health：连接/服务健康。
索引文档字段定义见 mapping.py；正文、向量不进入日志。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class BulkIndexResult:
    """一次 bulk 的结果。failed 为失败文档 ID 列表（非空时整体不通过 VERIFY）。"""

    indexed: int
    failed: list[str] = field(default_factory=list)


class SearchAdapterError(Exception):
    """检索引擎适配器错误。category/code 稳定，retryable 决定任务是否重试。"""

    def __init__(
        self,
        category: str,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status: int | None = None,
    ):
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status = status


class SearchAdapter(Protocol):
    """供应商无关的检索引擎适配器协议（Phase 4 覆盖 INDEX/VERIFY/CLEANUP）。"""

    def bulk_index(self, docs: list[dict], *, generation: str) -> BulkIndexResult: ...
    def delete_generation(self, generation: str) -> int: ...
    def count_by_generation(self, generation: str) -> int: ...
    def get(self, doc_id: str) -> dict | None: ...
    def sample(self, generation: str, limit: int = 3) -> list[dict]: ...
    def health(self) -> bool: ...
