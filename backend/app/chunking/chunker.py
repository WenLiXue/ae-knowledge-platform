"""真实文档切片（DD-19 §10）。

- 文本：以标题/段落/列表语义边界优先，目标 target_max、硬上限 hard_max、最小 min_tokens；
  相邻正文块间保留 overlap_tokens 的重叠（取自前块 body 尾部）；
- 表格：优先完整保留；超限按行拆分并重复表头（sheet_region 同策略）；
- 每个 Chunk 携带 heading_path、locator（元素引用）与 metadata_snapshot；
- 相同输入重复切片结果确定（幂等）；由流水线在事务内替换写入，避免重复 ordinal。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..parsing.schemas import ParsedDocument, ParsedElement
from .config import ChunkingConfig
from .tokens import estimate_tokens, is_cjk


@dataclass(frozen=True)
class ChunkSpec:
    """切片结果（与 knowledge.document_chunks 字段一一对应）。"""

    chunk_type: str  # paragraph / list / table / sheet_region
    content: str
    content_sha256: str
    heading_path: list
    locator: dict
    metadata_snapshot: dict
    token_count: int
    element_ids: list


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- 长文本 / 重叠辅助 ----

def _char_tail(line: str, limit_tokens: int) -> str:
    """返回 line 的尾部子串，token 估算不超过 limit_tokens。"""
    total = 0.0
    for i in range(len(line) - 1, -1, -1):
        total += 1.0 if is_cjk(line[i]) else 1.0 / 3.0
        if total >= limit_tokens:
            return line[i:]
    return line


def _body_tail(text: str, limit_tokens: int) -> str:
    """返回 text 的尾部（按行优先，单行超预算时按字符回退）。"""
    if limit_tokens <= 0 or not text:
        return ""
    lines = text.splitlines()
    acc: list[str] = []
    total = 0
    for line in reversed(lines):
        t = estimate_tokens(line)
        if acc and total + t > limit_tokens:
            break
        acc.append(line)
        total += t
        if total >= limit_tokens:
            break
    if acc:
        if estimate_tokens(acc[-1]) > limit_tokens:
            acc[-1] = _char_tail(acc[-1], limit_tokens)
        acc.reverse()
        return "\n".join(acc)
    return _char_tail(lines[-1], limit_tokens)


def _find_end(text: str, start: int, budget: int) -> int:
    """从 start 前进到 token 预算附近，优先落在分隔符边界。"""
    total = 0.0
    last_sep = -1
    for i in range(start, len(text)):
        ch = text[i]
        total += 1.0 if is_cjk(ch) else 1.0 / 3.0
        if ch in "\n，。；、！？ .\t":
            last_sep = i
        if total >= budget:
            if last_sep > start and i - last_sep <= budget:
                return last_sep + 1
            return i + 1
    return len(text)


def _overlap_start(text: str, end: int, overlap: int) -> int:
    """从 end 回退 overlap token 左右的起点。"""
    total = 0.0
    i = end - 1
    while i >= 0:
        total += 1.0 if is_cjk(text[i]) else 1.0 / 3.0
        if total >= overlap:
            return i
        i -= 1
    return 0


def _split_long_text(text: str, config: ChunkingConfig) -> list[str]:
    """单个元素超过硬上限时按字符拆块，相邻块带 overlap。"""
    budget = config.hard_max_tokens
    pieces: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = _find_end(text, start, budget)
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= n:
            break
        start = _overlap_start(text, end, config.overlap_tokens)
        if start >= end:
            start = end
    return pieces


# ---- 文本块构建 ----

class _TextChunk:
    __slots__ = ("heading", "heading_path", "overlap", "items", "element_ids", "locators", "list_only")

    def __init__(self, *, heading: str | None, heading_path: list, overlap: str):
        self.heading = heading
        self.heading_path: list[str] = list(heading_path or [])
        self.overlap = overlap or ""
        self.items: list[str] = []
        self.element_ids: list[str] = []
        self.locators: list[dict] = []
        self.list_only = not self.overlap  # 有重叠即视为混合文本块

    def body(self) -> str:
        parts = []
        if self.overlap:
            parts.append(self.overlap)
        parts.extend(self.items)
        return "\n".join(parts)

    def content(self) -> str:
        parts = []
        if self.heading:
            parts.append(self.heading)
        body = self.body()
        if body:
            parts.append(body)
        return "\n".join(parts)

    def tokens(self) -> int:
        return estimate_tokens(self.content())

    def add(self, el: ParsedElement, text: str) -> None:
        if not self.heading_path:
            self.heading_path = list(el.heading_path or [])
        self.items.append(text)
        self.element_ids.append(el.element_id)
        self.locators.append(dict(el.locator or {}))
        if el.type != "list_item":
            self.list_only = False


# ---- 表格 ----

def _render_table(columns: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(columns) + " |"]
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows:
        cells = row if len(row) == len(columns) else row + [""] * (len(columns) - len(row))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _table_spec(el: ParsedElement, render: str, snapshot: dict) -> ChunkSpec:
    return ChunkSpec(
        chunk_type="sheet_region" if el.type == "sheet_region" else "table",
        content=render,
        content_sha256=_sha256(render),
        heading_path=list(el.heading_path or []),
        locator={"element_ids": [el.element_id], "locators": [dict(el.locator or {})]},
        metadata_snapshot=snapshot,
        token_count=estimate_tokens(render),
        element_ids=[el.element_id],
    )


def _emit_table(el: ParsedElement, config: ChunkingConfig, snapshot: dict, out: list[ChunkSpec]) -> None:
    table = el.table
    if not isinstance(table, dict):
        return
    columns = table.get("columns")
    rows = table.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return  # 无标准结构的表格不产出独立 Chunk（不执行内容）
    columns = [str(c) for c in columns]
    rows = [[str(c) for c in row] for row in rows if isinstance(row, list)]

    header_render = _render_table(columns, [])
    header_tokens = estimate_tokens(header_render)
    budget = max(config.min_tokens, config.hard_max_tokens - header_tokens)
    group: list[list[str]] = []
    group_tokens = header_tokens

    def flush_group() -> None:
        nonlocal group, group_tokens
        if group:
            out.append(_table_spec(el, _render_table(columns, group), snapshot))
            group = []
            group_tokens = header_tokens

    for row in rows:
        row_tokens = estimate_tokens("| " + " | ".join(row) + " |")
        if group and (group_tokens + row_tokens > budget or len(group) >= config.max_table_split_rows):
            flush_group()
        group.append(row)
        group_tokens += row_tokens
    flush_group()


# ---- 主入口 ----

def chunk_document(
    parsed: ParsedDocument,
    *,
    metadata_snapshot: dict | None = None,
    config: ChunkingConfig | None = None,
) -> list[ChunkSpec]:
    """把 ParsedDocument 切成 ChunkSpec 列表。

    - 标题是章节边界，不产出独立 Chunk；标题文本作为其后正文块的内容前缀；
    - 空/纯导航输入返回空列表（不把页眉页脚/空白/纯标题作为独立 Chunk）。
    """
    config = config or ChunkingConfig()
    snapshot = dict(metadata_snapshot or {})
    out: list[ChunkSpec] = []

    section_heading: str | None = None
    section_path: list[str] = []
    pending_overlap = ""
    current: _TextChunk | None = None

    def emit_text() -> None:
        nonlocal current, pending_overlap
        if current is not None:
            if current.element_ids:
                out.append(
                    ChunkSpec(
                        chunk_type="list" if current.list_only else "paragraph",
                        content=current.content(),
                        content_sha256=_sha256(current.content()),
                        heading_path=current.heading_path,
                        locator={"element_ids": current.element_ids, "locators": current.locators},
                        metadata_snapshot=snapshot,
                        token_count=current.tokens(),
                        element_ids=current.element_ids,
                    )
                )
                pending_overlap = _body_tail(current.body(), config.overlap_tokens)
            current = None

    def new_text_chunk() -> None:
        nonlocal current, pending_overlap
        current = _TextChunk(heading=section_heading, heading_path=section_path, overlap=pending_overlap)
        pending_overlap = ""

    for el in parsed.elements:
        if el.type == "heading":
            emit_text()
            section_heading = el.text or None
            section_path = list(el.heading_path or [])
            pending_overlap = ""
            continue
        if el.type in ("table", "sheet_region"):
            emit_text()
            pending_overlap = ""
            _emit_table(el, config, snapshot, out)
            continue
        text = (el.text or "").strip()
        if not text:
            continue
        if current is None:
            new_text_chunk()
        el_tokens = estimate_tokens(text)
        cur_tokens = current.tokens()
        if cur_tokens > 0 and cur_tokens + el_tokens > config.target_max_tokens and cur_tokens >= config.min_tokens:
            emit_text()
            new_text_chunk()
        elif cur_tokens + el_tokens > config.hard_max_tokens:
            emit_text()
            new_text_chunk()
        if el_tokens > config.hard_max_tokens:
            # 单个元素超硬上限：拆成多块（块内带重叠）
            emit_text()
            prefix = section_heading if section_heading else None
            for piece in _split_long_text(text, config):
                content = f"{prefix}\n{piece}" if prefix else piece
                out.append(
                    ChunkSpec(
                        chunk_type="paragraph",
                        content=content,
                        content_sha256=_sha256(content),
                        heading_path=list(section_path),
                        locator={"element_ids": [el.element_id], "locators": [dict(el.locator or {})]},
                        metadata_snapshot=snapshot,
                        token_count=estimate_tokens(content),
                        element_ids=[el.element_id],
                    )
                )
            continue
        current.add(el, text)
    emit_text()
    return out
