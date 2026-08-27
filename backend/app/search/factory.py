"""检索引擎适配器工厂（DD-19 §11.2）。"""

from __future__ import annotations

from ..core.config import Settings, get_settings
from .base import SearchAdapter
from .fake import FakeSearchAdapter
from .opensearch import OpenSearchSearchAdapter
from .pgvector import PgVectorSearchAdapter


def get_search_adapter(settings: Settings | None = None) -> SearchAdapter:
    settings = settings or get_settings()
    engine = (settings.search_engine or "fake").casefold()
    if engine == "fake":
        return FakeSearchAdapter()
    if engine in {"pgvector", "postgres", "postgresql"}:
        return PgVectorSearchAdapter()
    if engine == "opensearch":
        return OpenSearchSearchAdapter(
            base_url=settings.opensearch_base_url,
            index_name=settings.search_index_name,
            username=settings.opensearch_username,
            password=settings.opensearch_password,
        )
    raise ValueError(f"未知检索引擎: {settings.search_engine}")
