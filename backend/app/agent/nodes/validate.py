"""validate_citations：确定性校验——引用属于本轮 evidence，source/version/chunk 一致，答案标记可解析。"""

from __future__ import annotations

from ..citations import validate_citation_drafts


def core_validate_citations(state: dict, ctx):
    errors = validate_citation_drafts(
        state.get("answer_blocks") or [],
        state.get("citation_drafts") or [],
        state.get("evidence") or [],
    )
    return {"validation_errors": errors}
