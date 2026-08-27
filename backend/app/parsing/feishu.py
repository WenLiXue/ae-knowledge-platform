"""真实飞书正文解析器（DD-19 §6）。

从 FETCH 写入的 raw 对象（FeishuContent.raw_payload）解析为版本化 ParsedDocument。
支持两种载体：
- blocks 形式（Fake/结构化）：raw_payload["blocks"] = [{type, text, ...}, ...]
- raw_content 形式（真实飞书 /raw_content）：raw_payload["raw_content"] = Markdown 文本
- sheet 形式：raw_payload["sheets"] = [{sheet_id, title, range, values}, ...]

正文按不可信数据处理：只做结构解析，不执行其中的指令、链接、宏或脚本（§2.3/§19）。
输出元素均带稳定 element_id 与 locator，同一输入重复解析结果一致（幂等）。
"""

from __future__ import annotations

import re

from .schemas import ParsedDocument, ParsedElement

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_RE = re.compile(r"^([-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^:?-{2,}:?$")

# 块类型 → ParsedElement.type（不可信/不支持的类型直接忽略，不执行其内容）
_BLOCK_TYPE_MAP = {
    "heading": "heading",
    "paragraph": "paragraph",
    "bulleted_list_item": "list_item",
    "ordered_list_item": "list_item",
    "list_item": "list_item",
    "table": "table",
}


def parse_feishu_payload(
    payload: dict | None,
    *,
    title: str = "",
    source_type: str = "docx",
) -> ParsedDocument:
    """解析 raw 对象为 ParsedDocument。空/非法输入返回空文档，不抛错。"""
    payload = payload or {}
    if payload.get("type") == "sheet" and isinstance(payload.get("sheets"), list):
        elements = _parse_sheets(payload)
        return ParsedDocument(
            title=title or str(payload.get("title") or ""),
            source_type="sheet",
            elements=elements,
            stats={
                "element_count": len(elements),
                "sheet_count": len(payload.get("sheets") or []),
                "truncated": bool(payload.get("truncated", False)),
            },
        )
    blocks = payload.get("blocks")
    if isinstance(blocks, list) and blocks:
        elements = _parse_blocks(blocks)
        doc_source = str(payload.get("type") or source_type)
        doc_title = title or str(payload.get("title") or "")
    else:
        text = payload.get("raw_content")
        if isinstance(text, str):
            elements = _parse_markdown(text)
            doc_source = source_type
            doc_title = title or str(payload.get("title") or "")
        else:
            elements = []
            doc_source = source_type
            doc_title = title or ""
    return ParsedDocument(
        title=doc_title,
        source_type=doc_source,
        elements=elements,
        stats={"element_count": len(elements), "truncated": False},
    )


def _parse_sheets(payload: dict) -> list[ParsedElement]:
    elements: list[ParsedElement] = []
    source_url = payload.get("source_url") if isinstance(payload.get("source_url"), str) else None
    spreadsheet_token = str(payload.get("spreadsheet_token") or "")
    for sheet in payload.get("sheets") or []:
        if not isinstance(sheet, dict):
            continue
        sheet_id = str(sheet.get("sheet_id") or "")
        sheet_title = str(sheet.get("title") or sheet_id or "工作表")
        heading_seq = len(elements)
        elements.append(
            _element(
                heading_seq,
                "heading",
                text=sheet_title,
                path=[],
                locator_extra={
                    "spreadsheet_token": spreadsheet_token,
                    "sheet_id": sheet_id,
                    "source_url": source_url,
                },
            )
        )
        values = _normalize_sheet_rows(sheet.get("values"))
        if not values:
            continue
        columns = values[0]
        rows = values[1:]
        actual_range = _sheet_range(sheet_id, values)
        region_seq = len(elements)
        elements.append(
            _element(
                region_seq,
                "sheet_region",
                table={"columns": columns, "rows": rows},
                path=[sheet_title],
                locator_extra={
                    "spreadsheet_token": spreadsheet_token,
                    "sheet_id": sheet_id,
                    "sheet_title": sheet_title,
                    "range": actual_range,
                    "source_url": source_url,
                },
            )
        )
    return elements


def _normalize_sheet_rows(value: object) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    rows = [
        [str(cell) if cell is not None else "" for cell in row]
        for row in value
        if isinstance(row, list)
    ]
    while rows and not any(cell.strip() for cell in rows[-1]):
        rows.pop()
    if not rows:
        return []
    width = max(len(row) for row in rows)
    return [(row + [""] * (width - len(row))) for row in rows]


def _sheet_range(sheet_id: str, rows: list[list[str]]) -> str:
    width = max(len(row) for row in rows)
    value = width
    letters: list[str] = []
    while value:
        value, remainder = divmod(value - 1, 26)
        letters.append(chr(ord("A") + remainder))
    end_column = "".join(reversed(letters)) or "A"
    return f"{sheet_id}!A1:{end_column}{len(rows)}"


def _parse_blocks(blocks: list) -> list[ParsedElement]:
    elements: list[ParsedElement] = []
    heading_stack: list[str] = []
    for seq, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        btype = str(block.get("type") or "paragraph")
        text = block.get("text")
        text = text if isinstance(text, str) else None
        element_type = _BLOCK_TYPE_MAP.get(btype)
        if element_type is None:
            continue
        if element_type == "heading":
            heading_text = (text or "").strip()
            # blocks 形式默认无标题层级：同级标题视为兄弟（顶层），新标题没有祖先
            heading_stack.clear()
            path = list(heading_stack)
            if heading_text:
                heading_stack.append(heading_text)
            elements.append(_element(seq, "heading", text=heading_text, path=path))
            continue
        if element_type == "table":
            table = block.get("table")
            if isinstance(table, dict):
                elements.append(_element(seq, "table", table=table, path=list(heading_stack)))
            elif text:
                elements.append(_element(seq, "table", text=text, path=list(heading_stack)))
            continue
        elements.append(_element(seq, element_type, text=(text or ""), path=list(heading_stack)))
    return elements


def _parse_markdown(text: str) -> list[ParsedElement]:
    elements: list[ParsedElement] = []
    heading_stack: list[str] = []
    lines = text.splitlines()
    n = len(lines)
    i = 0
    seq = 0
    while i < n:
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        # 表格：连续以 | 开头的行，跳过分隔行，表头 + 数据行。
        if stripped.startswith("|") and "|" in stripped[1:]:
            rows: list[list[str]] = []
            while i < n and lines[i].strip().startswith("|"):
                cells = _split_cells(lines[i].strip())
                if all(_TABLE_SEP_RE.match(c.strip()) for c in cells if c.strip()):
                    i += 1
                    continue
                rows.append(cells)
                i += 1
            if rows:
                columns = rows[0] if rows else []
                table = {"columns": columns, "rows": rows[1:] if len(rows) > 1 else []}
                elements.append(_element(seq, "table", table=table, path=list(heading_stack)))
                seq += 1
            continue
        # 标题：回退到同层/更上层后入栈。
        hm = _HEADING_RE.match(stripped)
        if hm:
            level = len(hm.group(1))
            heading_text = hm.group(2).strip()
            path = list(heading_stack)
            while len(heading_stack) >= level:
                heading_stack.pop()
            if heading_text:
                heading_stack.append(heading_text)
            elements.append(_element(seq, "heading", text=heading_text, path=path))
            seq += 1
            i += 1
            continue
        # 列表项。
        lm = _LIST_RE.match(stripped)
        if lm:
            elements.append(_element(seq, "list_item", text=lm.group(2).strip(), path=list(heading_stack)))
            seq += 1
            i += 1
            continue
        # 段落：收集到下一个结构边界，内部空白折叠为一个空格。
        buf = [stripped]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (
                not nxt
                or nxt.startswith("|")
                or _HEADING_RE.match(nxt)
                or _LIST_RE.match(nxt)
            ):
                break
            buf.append(nxt)
            i += 1
        elements.append(_element(seq, "paragraph", text=" ".join(buf), path=list(heading_stack)))
        seq += 1
    return elements


def _split_cells(row: str) -> list[str]:
    body = row.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip() for c in body.split("|")]


def _element(
    seq: int,
    element_type: str,
    *,
    text: str | None = None,
    table: dict | None = None,
    path: list[str],
    locator_extra: dict | None = None,
) -> ParsedElement:
    element_id = f"el-{seq:04d}"
    locator = {"element_id": element_id, "index": seq}
    if locator_extra:
        locator.update({key: value for key, value in locator_extra.items() if value is not None})
    return ParsedElement(
        element_id=element_id,
        type=element_type,  # type: ignore[arg-type]  # 已由调用方映射到合法 Literal
        text=text,
        table=table,
        heading_path=path,
        locator=locator,
    )
