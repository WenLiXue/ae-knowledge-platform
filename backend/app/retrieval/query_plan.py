"""查询计划构造（DD-19 §12.1）。

Phase 5 无查询理解模型：operation 默认 ANSWER、normalized_question=问题原文去空白、
query_texts=[normalized_question]、needs_clarification=False。显式过滤条件必须通过
``validate_filters``（ID 全部来自数据库目录）才会进入 QueryPlan。
Phase 6 查询理解将在此构造 query_texts/operation/required_fields。
"""

from __future__ import annotations

from .errors import RetrievalError
from .filters import validate_filters
from .schemas import QueryPlan, RetrievalFilters

_MAX_QUESTION_CHARS = 4000


def build_query_plan(
    db, question: str, filters: RetrievalFilters | None = None
) -> QueryPlan:
    q = (question or "").strip()
    if not q:
        raise RetrievalError("VALIDATION", "EMPTY_QUESTION", "问题不能为空", retryable=False)
    if len(q) > _MAX_QUESTION_CHARS:
        raise RetrievalError(
            "VALIDATION", "QUESTION_TOO_LONG", "问题过长（上限 4000 字符）", retryable=False
        )
    filters = filters or RetrievalFilters()
    validate_filters(db, filters)
    return QueryPlan(
        normalized_question=q,
        query_texts=[q],
        product_id=filters.product_id,
        version_ids=list(filters.version_ids),
        document_type_ids=list(filters.document_type_ids),
    )
