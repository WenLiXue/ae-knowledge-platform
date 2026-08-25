"""版本化 ParsedDocument 契约（DD-19 §6.1）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ParsedElement(BaseModel):
    """解析后的结构化元素，携带稳定 locator 与标题路径。"""

    element_id: str
    type: Literal["heading", "paragraph", "list_item", "table", "sheet_region"]
    text: str | None = None
    table: dict | None = None
    heading_path: list[str] = Field(default_factory=list)
    locator: dict = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    """一次解析的标准产物（schema_version=1.0）。"""

    schema_version: Literal["1.0"] = "1.0"
    title: str = ""
    source_type: str = "docx"
    elements: list[ParsedElement] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)
