"""检索引擎适配器（DD-19 §11.2）。"""

from .base import BulkIndexResult, SearchAdapter, SearchAdapterError
from .factory import get_search_adapter
from .fake import FakeSearchAdapter
from .mapping import MAPPING_VERSION, doc_id
from .opensearch import OpenSearchSearchAdapter

__all__ = [
    "BulkIndexResult",
    "FakeSearchAdapter",
    "MAPPING_VERSION",
    "OpenSearchSearchAdapter",
    "SearchAdapter",
    "SearchAdapterError",
    "doc_id",
    "get_search_adapter",
]
