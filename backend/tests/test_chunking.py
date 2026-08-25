"""真实切片（DD-19 §10）的行为测试。

覆盖：token 估算、文本块分组与重叠、标题前缀与标题路径、表格完整保留与按行拆分
（重复表头）、列表块类型、locator/元素引用、metadata_snapshot 盖章、超大段落拆分、
幂等（同一输入结果确定）、空文档不产出 Chunk。
"""

from __future__ import annotations

from app.chunking import ChunkingConfig, chunk_document, estimate_tokens
from app.parsing import ParsedDocument, ParsedElement


def _el(seq: int, etype: str, text: str, path: list[str] | None = None) -> ParsedElement:
    return ParsedElement(
        element_id=f"el-{seq:04d}",
        type=etype,  # type: ignore[arg-type]
        text=text,
        heading_path=path or [],
        locator={"element_id": f"el-{seq:04d}", "index": seq},
    )


def _table(seq: int, columns: list[str], rows: list[list[str]], path: list[str] | None = None) -> ParsedElement:
    return ParsedElement(
        element_id=f"el-{seq:04d}",
        type="table",
        table={"columns": columns, "rows": rows},
        heading_path=path or [],
        locator={"element_id": f"el-{seq:04d}", "index": seq},
    )


# ---- token 估算 ----

def test_estimate_tokens_cjk_and_other() -> None:
    assert estimate_tokens("你好世界") == 4
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("abcdef") == 2
    assert estimate_tokens("") == 0
    # 混合：2 个 CJK + 2 个非 CJK → 2 + ceil(2/3) = 3
    assert estimate_tokens("配置v2") == 3


# ---- 文本分组与标题 ----

def test_headings_and_paragraphs_form_section_chunks() -> None:
    parsed = ParsedDocument(
        title="文档",
        source_type="docx",
        elements=[
            _el(0, "heading", "第一章 概述"),
            _el(1, "paragraph", "第一段正文内容。", path=["第一章 概述"]),
            _el(2, "paragraph", "第二段正文内容。", path=["第一章 概述"]),
            _el(3, "heading", "第二章 配置"),
            _el(4, "list_item", "选项 A", path=["第二章 配置"]),
            _el(5, "list_item", "选项 B", path=["第二章 配置"]),
        ],
    )
    chunks = chunk_document(parsed)
    assert [c.chunk_type for c in chunks] == ["paragraph", "list"]
    assert chunks[0].heading_path == ["第一章 概述"]
    assert chunks[0].content == "第一章 概述\n第一段正文内容。\n第二段正文内容。"
    assert chunks[0].element_ids == ["el-0001", "el-0002"]
    # locator 可回溯：每个元素引用其原始 locator
    assert chunks[0].locator["element_ids"] == ["el-0001", "el-0002"]
    assert chunks[0].locator["locators"][0]["index"] == 1
    assert chunks[1].heading_path == ["第二章 配置"]
    assert chunks[1].content == "第二章 配置\n选项 A\n选项 B"


def test_small_config_forces_split_with_overlap() -> None:
    config = ChunkingConfig(
        target_min_tokens=5, target_max_tokens=20, hard_max_tokens=30, min_tokens=5, overlap_tokens=5
    )
    parsed = ParsedDocument(
        title="长文",
        source_type="docx",
        elements=[
            _el(0, "heading", "第一章"),
            _el(1, "paragraph", "这是第一段的内容，用来构成第一个切片。", path=["第一章"]),
            _el(2, "paragraph", "这是第二段的内容，用来构成下一个切片。", path=["第一章"]),
            _el(3, "paragraph", "这是第三段的内容，用来构成再下一个切片。", path=["第一章"]),
            _el(4, "paragraph", "这是第四段的内容，用来构成末尾切片。", path=["第一章"]),
        ],
    )
    chunks = chunk_document(parsed, config=config)
    assert len(chunks) >= 2
    # 每个切片 token 不超硬上限
    assert all(c.token_count <= config.hard_max_tokens for c in chunks)
    # 相邻正文块重叠：后一块 body 首行 = 前一块 body 尾部，且不超重叠预算
    body0 = chunks[0].content.split("\n", 1)[1]
    body1 = chunks[1].content.split("\n", 1)[1]
    first_line = body1.splitlines()[0]
    assert body0.endswith(first_line)
    assert estimate_tokens(first_line) <= config.overlap_tokens


# ---- 表格 ----

def test_small_table_is_one_chunk() -> None:
    parsed = ParsedDocument(
        title="规格",
        source_type="docx",
        elements=[
            _el(0, "heading", "产品规格"),
            _table(1, ["型号", "内存"], [["T90000", "256GB"], ["T90001", "512GB"]], path=["产品规格"]),
        ],
    )
    chunks = chunk_document(parsed)
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "table"
    assert "| 型号 | 内存 |" in chunks[0].content
    assert "| T90000 | 256GB |" in chunks[0].content
    assert chunks[0].heading_path == ["产品规格"]
    assert chunks[0].element_ids == ["el-0001"]


def test_large_table_splits_by_row_with_repeated_header() -> None:
    config = ChunkingConfig(
        target_min_tokens=10, target_max_tokens=40, hard_max_tokens=50,
        overlap_tokens=0, max_table_split_rows=2,
    )
    rows = [[f"型号{i}", f"值{i}"] for i in range(6)]
    parsed = ParsedDocument(
        title="大表",
        source_type="docx",
        elements=[_table(0, ["型号", "值"], rows)],
    )
    chunks = chunk_document(parsed, config=config)
    assert len(chunks) > 1
    assert all(c.chunk_type == "table" for c in chunks)
    # 每块都重复表头（含表头行）
    assert all("| 型号 | 值 |" in c.content for c in chunks)
    assert all(c.token_count <= config.hard_max_tokens for c in chunks)


# ---- 幂等 / 边界 ----

def test_chunking_is_deterministic() -> None:
    parsed = ParsedDocument(
        title="幂等",
        source_type="docx",
        elements=[
            _el(0, "heading", "第一章"),
            _el(1, "paragraph", "正文内容若干。", path=["第一章"]),
            _table(2, ["A"], [["1"]]),
        ],
    )
    a = chunk_document(parsed)
    b = chunk_document(parsed)
    assert [c.__dict__ for c in a] == [c.__dict__ for c in b]


def test_empty_document_produces_no_chunks() -> None:
    parsed = ParsedDocument(title="空", source_type="docx", elements=[])
    assert chunk_document(parsed) == []


def test_metadata_snapshot_stamped_on_each_chunk() -> None:
    snapshot = {"product_code": "TDA", "document_type_code": "test-report"}
    parsed = ParsedDocument(
        title="元数据",
        source_type="docx",
        elements=[_el(0, "paragraph", "正文内容。")],
    )
    chunks = chunk_document(parsed, metadata_snapshot=snapshot)
    assert len(chunks) == 1
    assert chunks[0].metadata_snapshot == snapshot


def test_content_sha256_and_token_count_filled() -> None:
    parsed = ParsedDocument(
        title="字段",
        source_type="docx",
        elements=[_el(0, "paragraph", "需要校验 sha 与 token 计数的正文。")],
    )
    chunk = chunk_document(parsed)[0]
    assert len(chunk.content_sha256) == 64
    assert chunk.token_count == estimate_tokens(chunk.content)


def test_oversized_paragraph_split_within_hard_max() -> None:
    config = ChunkingConfig(
        target_min_tokens=10, target_max_tokens=20, hard_max_tokens=40, min_tokens=5, overlap_tokens=5
    )
    # 单个段落远超硬上限（120 个 CJK 字符 ≈ 120 tokens）
    long_text = "内容" * 120
    parsed = ParsedDocument(
        title="超长",
        source_type="docx",
        elements=[_el(0, "paragraph", long_text)],
    )
    chunks = chunk_document(parsed, config=config)
    assert len(chunks) > 1
    assert all(c.token_count <= config.hard_max_tokens for c in chunks)
    assert all(c.element_ids == ["el-0000"] for c in chunks)
