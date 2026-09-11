"""查询计划构造（DD-19 §12.1）。

Phase 5 无查询理解模型：operation 默认 ANSWER、normalized_question=问题原文去空白、
query_texts=[normalized_question]、needs_clarification=False。显式过滤条件必须通过
``validate_filters``（ID 全部来自数据库目录）才会进入 QueryPlan。
Phase 6 查询理解将在此构造 query_texts/operation/required_fields。
"""

from __future__ import annotations

import re

from .errors import RetrievalError
from .filters import validate_filters
from .schemas import QueryPlan, RetrievalFilters

_MAX_QUESTION_CHARS = 4000
_ENTITY_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{1,8}\d{2,}[A-Za-z0-9-]*")


def _required_terms(question: str) -> list[str]:
    """提取需要逐一覆盖的稳定实体 token（型号、版本、产品编号）。"""
    seen: set[str] = set()
    terms: list[str] = []
    for match in _ENTITY_TOKEN_RE.finditer(question):
        value = match.group(0)
        key = value.upper()
        if key not in seen:
            seen.add(key)
            terms.append(value)
    return terms


def build_query_plan(
    db, question: str, filters: RetrievalFilters | None = None, *, operation: str = "ANSWER"
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
    required_terms = _required_terms(q)
    # 保留原始问题，同时为每个稳定实体建立独立召回路由。这样中文描述词
    # 的 AND 约束不会把型号 token 一起过滤掉。
    query_texts = [q]
    query_texts.extend(term for term in required_terms if term not in query_texts)
    return QueryPlan(
        operation=operation,
        normalized_question=q,
        query_texts=query_texts,
        required_terms=required_terms,
        product_id=filters.product_id,
        version_ids=list(filters.version_ids),
        document_type_ids=list(filters.document_type_ids),
    )
