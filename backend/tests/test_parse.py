"""ParsedDocument 契约与真实飞书解析器测试（DD-19 Phase 2）。"""

from app.parsing import parse_feishu_payload


def test_blocks_form_parses_headings_and_paragraphs() -> None:
    parsed = parse_feishu_payload(
        {
            "type": "docx",
            "blocks": [
                {"type": "heading", "text": "第一章 概述"},
                {"type": "paragraph", "text": "这是正文。"},
                {"type": "heading", "text": "第二章 规格"},
            ],
        },
        title="规格文档",
    )
    assert parsed.schema_version == "1.0"
    assert parsed.title == "规格文档"
    assert parsed.source_type == "docx"
    assert [e.type for e in parsed.elements] == ["heading", "paragraph", "heading"]
    # heading_path：非标题元素携带祖先标题；标题自身只携带其父级
    assert parsed.elements[0].heading_path == []
    assert parsed.elements[1].heading_path == ["第一章 概述"]
    assert parsed.elements[2].heading_path == []
    # locator 与 element_id 稳定一致
    assert parsed.elements[1].locator["element_id"] == parsed.elements[1].element_id
    assert parsed.stats["element_count"] == 3


def test_raw_content_parses_markdown_structure() -> None:
    text = (
        "# 产品规格\n"
        "T90000 采用 AMD EPYC 7H12。\n\n"
        "- 支持旁路部署\n"
        "- 支持网桥模式\n\n"
        "## 配置\n"
        "| 型号 | 内存 |\n"
        "| --- | --- |\n"
        "| T90000 | 256GB |\n"
        "| T90001 | 512GB |\n"
    )
    parsed = parse_feishu_payload({"document_id": "x", "raw_content": text}, title="规格")
    assert [e.type for e in parsed.elements] == [
        "heading", "paragraph", "list_item", "list_item", "heading", "table",
    ]
    table = parsed.elements[5].table
    assert table["columns"] == ["型号", "内存"]
    assert table["rows"] == [["T90000", "256GB"], ["T90001", "512GB"]]
    # 表格位于「产品规格 > 配置」标题路径下
    assert parsed.elements[5].heading_path == ["产品规格", "配置"]


def test_parse_is_deterministic() -> None:
    payload = {"raw_content": "# A\n\n段落一。\n\n- x\n- y\n"}
    assert parse_feishu_payload(payload).model_dump() == parse_feishu_payload(payload).model_dump()


def test_parse_empty_and_malformed() -> None:
    assert parse_feishu_payload({}).elements == []
    assert parse_feishu_payload(None).elements == []
    parsed = parse_feishu_payload({"raw_content": 123})
    assert parsed.elements == []
    assert parsed.stats["element_count"] == 0
