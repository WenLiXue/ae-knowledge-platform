"""文档解析：ParsedDocument 契约与飞书真实解析器（DD-19 §6）。"""

from .feishu import parse_feishu_payload
from .schemas import ParsedDocument, ParsedElement

__all__ = ["ParsedDocument", "ParsedElement", "parse_feishu_payload"]
