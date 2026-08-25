"""检索过滤与活动版本解析（DD-19 §12.2、DD-07 §6.2）。

- 只召回 QUERYABLE 来源的 current_version_id 且状态 READY、index_generation 非空
  的版本（AC-RAG-001：当前版本/当前 generation）；
- 显式产品/版本/文档类型条件在此基础上收窄，所有 ID 必须来自数据库目录
  （AC-RAG-002、§12.1 白名单）；
- 筛选后为空不自动放宽范围（DD-07 §7.3）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.catalog import DocumentType, Product, ProductVersion, SourcePriority
from ..db.models.knowledge import DocumentVersion, KnowledgeSource
from ..db.models.rag import DocumentMetadata
from .errors import RetrievalError
from .schemas import RetrievalFilters


@dataclass(frozen=True)
class VersionRef:
    """一个可查询版本（来源 current_version，已激活 generation）。"""

    version_id: uuid.UUID
    source_id: uuid.UUID
    generation: str
    display_name: str
    source_modified_at: datetime | None
    source_priority: int = 0


def validate_filters(db: Session, filters: RetrievalFilters | None) -> None:
    """校验过滤 ID 全部来自数据库目录；版本必须属于所选产品（DD-07 §4.1）。"""
    if filters is None:
        return
    if filters.product_id is not None:
        product = db.get(Product, filters.product_id)
        if product is None:
            raise RetrievalError(
                "VALIDATION", "FILTER_PRODUCT_NOT_FOUND", "筛选的产品不存在", retryable=False
            )
    for vid in filters.version_ids:
        version = db.get(ProductVersion, vid)
        if version is None:
            raise RetrievalError(
                "VALIDATION", "FILTER_VERSION_NOT_FOUND", "筛选的版本不存在", retryable=False
            )
        if filters.product_id is not None and version.product_id != filters.product_id:
            raise RetrievalError(
                "VALIDATION",
                "FILTER_VERSION_PRODUCT_MISMATCH",
                "筛选的版本不属于所选产品",
                retryable=False,
            )
    for dtid in filters.document_type_ids:
        if db.get(DocumentType, dtid) is None:
            raise RetrievalError(
                "VALIDATION", "FILTER_DOC_TYPE_NOT_FOUND", "筛选的文档类型不存在", retryable=False
            )


def _load_source_priorities(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(SourcePriority).where(SourcePriority.status == "ENABLED")
    ).scalars()
    return {row.source_code: row.priority for row in rows}


def resolve_active_versions(
    db: Session, filters: RetrievalFilters | None = None
) -> list[VersionRef]:
    """解析可查询版本：校验过滤 → 取 QUERYABLE current READY 版本 → 应用过滤收窄。"""
    validate_filters(db, filters)

    rows = db.execute(
        select(DocumentVersion, KnowledgeSource)
        .join(KnowledgeSource, KnowledgeSource.id == DocumentVersion.source_id)
        .where(
            KnowledgeSource.status == "QUERYABLE",
            KnowledgeSource.current_version_id == DocumentVersion.id,
            DocumentVersion.status == "READY",
            DocumentVersion.index_generation.isnot(None),
        )
    ).all()
    if not rows:
        return []

    priorities = _load_source_priorities(db)
    refs: list[VersionRef] = []
    for version, source in rows:
        refs.append(
            VersionRef(
                version_id=version.id,
                source_id=source.id,
                generation=version.index_generation,
                display_name=source.display_name,
                source_modified_at=version.source_modified_at,
                source_priority=priorities.get(source.source_type, 0),
            )
        )

    if filters is not None and (filters.product_id or filters.version_ids or filters.document_type_ids):
        meta_rows = db.execute(
            select(DocumentMetadata.version_id, DocumentMetadata.product_id,
                   DocumentMetadata.product_version_id, DocumentMetadata.document_type_id)
            .where(DocumentMetadata.version_id.in_([r.version_id for r in refs]))
        ).all()
        meta_by_version = {row.version_id: row for row in meta_rows}

        def _keep(ref: VersionRef) -> bool:
            meta = meta_by_version.get(ref.version_id)
            if meta is None:
                return False  # 有过滤条件时缺元数据不能匹配任何条件
            if filters.product_id is not None and meta.product_id != filters.product_id:
                return False
            if filters.version_ids and meta.product_version_id not in filters.version_ids:
                return False
            if filters.document_type_ids and meta.document_type_id not in filters.document_type_ids:
                return False
            return True

        refs = [ref for ref in refs if _keep(ref)]

    refs.sort(key=lambda r: r.display_name)
    return refs


def recheck_active_version_ids(db: Session) -> set[str]:
    """证据选择前复核（DD-07 §6.2）：重新取当前可查询版本 ID，索引候选只允许来自这些版本。

    索引可能因异步下线短暂滞后，不能在 Rerank 后仅依赖索引布尔字段。
    """
    rows = db.execute(
        select(DocumentVersion.id)
        .join(KnowledgeSource, KnowledgeSource.id == DocumentVersion.source_id)
        .where(
            KnowledgeSource.status == "QUERYABLE",
            KnowledgeSource.current_version_id == DocumentVersion.id,
            DocumentVersion.status == "READY",
        )
    ).scalars()
    return {str(vid) for vid in rows}
