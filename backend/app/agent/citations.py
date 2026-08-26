"""引用构建与校验（DD-21 §10.2）。

- build_citations：证据 → AnswerCitation 行（来源定位来自数据库，不用模型生成 URL）；
- map_blocks：GeneratedAnswer 块 → 带 citation_nos 的序列化块；
- validate_citation_drafts：引用必须属于本轮证据，source/version/chunk 一致。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.catalog import DocumentType, ProductVersion
from ..db.models.conversation import AnswerCitation
from ..db.models.knowledge import FeishuSourceDetail
from ..db.models.rag import DocumentMetadata


def build_citations(db: Session, answer_id, evidence) -> list[dict]:
    """把证据转引用快照（DD-10 §6）：来源/版本/标题/章节/locator/摘录/原文链接/更新时间。

    original_url 来自 FeishuSourceDetail（数据库保存的真实来源），不由模型生成。
    """
    version_ids = [ev.document_version_id for ev in evidence if ev.document_version_id]
    source_ids = [ev.source_id for ev in evidence if ev.source_id]

    doc_type_by_version: dict[uuid.UUID, str] = {}
    version_label_by_version: dict[uuid.UUID, str] = {}
    if version_ids:
        meta_rows = db.execute(
            select(DocumentMetadata, DocumentType)
            .join(DocumentType, DocumentType.id == DocumentMetadata.document_type_id)
            .where(DocumentMetadata.version_id.in_(version_ids))
        ).all()
        for meta, doc_type in meta_rows:
            doc_type_by_version[meta.version_id] = doc_type.code
        pv_rows = db.execute(
            select(DocumentMetadata.version_id, ProductVersion.version_code)
            .join(ProductVersion, ProductVersion.id == DocumentMetadata.product_version_id)
            .where(DocumentMetadata.version_id.in_(version_ids))
        ).all()
        for version_id, code in pv_rows:
            version_label_by_version[version_id] = code

    url_by_source: dict[uuid.UUID, str] = {}
    if source_ids:
        url_rows = db.execute(
            select(FeishuSourceDetail.source_id, FeishuSourceDetail.original_url).where(
                FeishuSourceDetail.source_id.in_(source_ids)
            )
        ).all()
        url_by_source = {source_id: url for source_id, url in url_rows if url}

    rows: list[dict] = []
    for no, ev in enumerate(evidence, start=1):
        excerpt = ev.content
        if len(excerpt) > 500:
            excerpt = excerpt[:500] + "…"
        rows.append(
            {
                "answer_id": answer_id,
                "citation_no": no,
                "source_id": ev.source_id,
                "version_id": ev.document_version_id,
                "chunk_id": ev.chunk_id,
                "document_title": ev.title,
                "document_type_code": doc_type_by_version.get(ev.document_version_id),
                "version_label": version_label_by_version.get(ev.document_version_id),
                "heading_path": list(ev.heading_path),
                "locator_json": ev.locator,
                "excerpt": excerpt,
                "original_url": url_by_source.get(ev.source_id),
                "source_updated_at": ev.source_updated_at,
            }
        )
    return rows


def map_blocks(generated, citations_data: list[dict]) -> list[dict]:
    """GeneratedAnswer 块 → 序列化块（citation_ids E{n} → citation_no n）。"""
    blocks: list[dict] = []
    for i, block in enumerate(generated.blocks, start=1):
        citation_nos: list[int] = []
        for cid in block.citation_ids:
            if cid.startswith("E"):
                try:
                    no = int(cid[1:])
                    if 1 <= no <= len(citations_data):
                        citation_nos.append(no)
                except ValueError:
                    continue
        blocks.append(
            {
                "block_id": f"b{i}",
                "type": block.type,
                "content": block.content,
                "citation_nos": citation_nos,
            }
        )
    return blocks


def validate_citation_drafts(
    blocks: list[dict],
    citation_drafts: list[dict],
    evidence: list[dict],
) -> list[str]:
    """确定性校验：引用编号在本轮证据内；事实块必须有引用；chunk 属于本轮证据。

    返回错误列表；空列表表示通过。
    """
    errors: list[str] = []
    chunk_ids = {str(e.get("chunk_id")) for e in evidence}

    for block in blocks:
        if block.get("type") in ("paragraph", "table", "list"):
            if not block.get("citation_nos"):
                errors.append(f"事实块 {block.get('block_id')} 缺少引用")
            for no in block.get("citation_nos", []):
                if not (1 <= int(no) <= len(evidence)):
                    errors.append(f"引用编号 {no} 不在本轮证据范围")
    for draft in citation_drafts:
        if draft.get("chunk_id") is not None and str(draft.get("chunk_id")) not in chunk_ids:
            errors.append(f"引用 chunk {draft.get('chunk_id')} 不属于本轮证据")
        if draft.get("original_url"):
            if not _looks_database_url(draft.get("original_url")):
                errors.append("引用包含不安全的来源地址")
    return errors


def _looks_database_url(url: str) -> bool:
    """防御：仅接受 http(s)，且不带凭证；模型生成的 URL 不进入原文地址。"""
    if not isinstance(url, str):
        return False
    lowered = url.strip().lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        return False
    return "@" not in lowered.split("://", 1)[-1]


def build_citation_rows(answer_id, citation_drafts: list[dict]) -> list[AnswerCitation]:
    """把引用草稿转为 AnswerCitation 实体（answer_id 已确定）。"""
    rows = []
    for draft in citation_drafts:
        row = AnswerCitation(answer_id=answer_id)
        for key, value in draft.items():
            if key == "answer_id":
                continue
            setattr(row, key, value)
        rows.append(row)
    return rows
