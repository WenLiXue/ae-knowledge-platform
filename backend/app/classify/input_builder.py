"""分类输入构造（DD-19 §8.2、DD-05 §5）。

按预算从 ParsedDocument 选择受控文本窗口：
- 标题、全部标题（一/二级优先）、摘要/前言/结论章节、各章节首段、
  表格表头 + 代表行、命中产品/版本术语的上下文；
- 每块带稳定 locator_id（引用源元素 element_id），按文档顺序去重；
- 预算超限即截断并记录，不发送整篇长文档。

输入哈希：
    SHA-256(content_sha256 + classification_config_revision + model_key
            + model_revision + prompt_revision + input_builder_revision)
相同 version + input_hash 只保留一个有效结果（DD-05 §9）。
"""

from __future__ import annotations

import hashlib

from ..parsing.schemas import ParsedDocument
from .config import DEFAULT_BUDGET
from .schemas import EvidenceBlock

# 摘要/前言/结论类章节标题命中词（大小写不敏感）
_SECTION_KEYWORDS = (
    "摘要", "简介", "概述", "概要", "前言", "结论", "总结",
    "abstract", "summary", "introduction", "overview", "conclusion",
)


def compute_input_hash(
    *,
    content_sha256: str | None,
    config_revision: int | None = 0,
    model_key: str | None = "",
    model_revision: int | None = None,
    prompt_revision: str | None = "",
    input_builder_revision: str | None = "",
) -> str:
    """输入哈希：配置/模型/Prompt 任一变化都会形成新哈希（DD-05 §9）。"""
    parts = [
        content_sha256 or "",
        str(config_revision if config_revision is not None else 0),
        model_key or "",
        str(model_revision if model_revision is not None else 0),
        prompt_revision or "",
        input_builder_revision or "",
    ]
    return hashlib.sha256("+".join(parts).encode("utf-8")).hexdigest()


def _term_set(taxonomy: dict) -> set[str]:
    """产品/版本稳定 code 与名称集合（大小写不敏感），用于上下文命中。"""
    terms: set[str] = set()
    for product in taxonomy.get("products") or []:
        for value in (product.get("code"), product.get("name")):
            if value:
                terms.add(str(value).casefold())
    for version in taxonomy.get("product_versions") or []:
        for value in (version.get("code"), version.get("product_code")):
            if value:
                terms.add(str(value).casefold())
    return terms


def _matches_term(text: str, terms: set[str]) -> bool:
    low = text.casefold()
    return any(term and term in low for term in terms)


def _is_section_keyword(text: str | None) -> bool:
    if not text:
        return False
    low = text.casefold()
    return any(keyword in low for keyword in _SECTION_KEYWORDS)


def build_input_blocks(
    parsed: ParsedDocument,
    taxonomy: dict,
    budget: dict | None = None,
) -> tuple[list[EvidenceBlock], dict]:
    """按预算选择输入块。返回 (blocks, selection_stats)。

    stats: {"included_blocks": int, "term_matches": int, "truncated": bool}
    """
    effective = dict(DEFAULT_BUDGET)
    if budget:
        effective.update({k: v for k, v in budget.items() if v is not None})

    terms = _term_set(taxonomy)
    blocks: list[EvidenceBlock] = []
    total_chars = 0
    truncated = False
    term_matches = 0
    max_blocks = int(effective["max_blocks"])
    max_chars_per_block = int(effective["max_chars_per_block"])
    total_cap = int(effective["total_chars"])
    max_table_rows = int(effective["max_table_rows"])

    def _take(text: str) -> str | None:
        """预算内截断文本；超预算返回 None 并置截断标记。空文本返回 None。"""
        nonlocal total_chars, truncated
        text = (text or "").strip()
        if not text:
            return None
        if len(text) > max_chars_per_block:
            text = text[:max_chars_per_block]
        if total_chars + len(text) > total_cap:
            truncated = True
            return None
        total_chars += len(text)
        return text

    # 标题块
    title_text = _take(parsed.title)
    if title_text is not None:
        blocks.append(
            EvidenceBlock(locator_id="title", heading_path=[], block_type="title", text=title_text)
        )

    global_first_para = True
    section_intro_added = False
    for element in parsed.elements:
        if truncated or len(blocks) >= max_blocks:
            truncated = truncated or len(blocks) >= max_blocks
            break
        path = list(element.heading_path or [])
        raw_text = (element.text or "").strip()

        if element.type == "heading":
            if raw_text:
                taken = _take(raw_text)
                if taken is not None:
                    blocks.append(
                        EvidenceBlock(
                            locator_id=element.element_id,
                            heading_path=path,
                            block_type="heading",
                            text=taken,
                        )
                    )
            section_intro_added = False
            continue

        if element.type == "paragraph":
            section_label = path[-1] if path else None
            is_first_para = global_first_para
            is_section_intro = not section_intro_added
            is_keyword_section = _is_section_keyword(section_label)
            term_hit = _matches_term(raw_text, terms)
            if is_first_para or is_section_intro or is_keyword_section or term_hit:
                if term_hit:
                    term_matches += 1
                taken = _take(raw_text)
                if taken is not None:
                    blocks.append(
                        EvidenceBlock(
                            locator_id=element.element_id,
                            heading_path=path,
                            block_type="paragraph",
                            text=taken,
                        )
                    )
                    global_first_para = False
                    section_intro_added = True
            continue

        if element.type == "list_item":
            if _matches_term(raw_text, terms):
                term_matches += 1
                taken = _take(raw_text)
                if taken is not None:
                    blocks.append(
                        EvidenceBlock(
                            locator_id=element.element_id,
                            heading_path=path,
                            block_type="list_item",
                            text=taken,
                        )
                    )
            continue

        if element.type == "table":
            table = element.table or {}
            columns = table.get("columns") or []
            rows = table.get("rows") or []
            header_text = _take("表: " + " | ".join(str(c) for c in columns))
            if header_text is not None:
                blocks.append(
                    EvidenceBlock(
                        locator_id=f"{element.element_id}:h",
                        heading_path=path,
                        block_type="table_header",
                        text=header_text,
                    )
                )
            for idx, row in enumerate(rows[:max_table_rows]):
                row_text = _take(" | ".join(str(c) for c in row))
                if row_text is not None:
                    blocks.append(
                        EvidenceBlock(
                            locator_id=f"{element.element_id}:r{idx}",
                            heading_path=path,
                            block_type="table_row",
                            text=row_text,
                        )
                    )
            continue

    stats = {
        "included_blocks": len(blocks),
        "term_matches": term_matches,
        "truncated": truncated,
    }
    return blocks, stats
