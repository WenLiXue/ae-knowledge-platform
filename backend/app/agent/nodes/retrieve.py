"""retrieve：直接调用现有 RetrievalService，不复制查询计划/BM25/向量/融合/Rerank 逻辑。"""

from __future__ import annotations

import uuid

from ...retrieval.errors import RetrievalError
from ...retrieval.schemas import RetrievalFilters
from ..state import evidence_to_dict
from . import dedupe_flags


def _filters_from_snapshot(snapshot: dict) -> RetrievalFilters:
    def _u(value):
        return uuid.UUID(str(value)) if value else None

    return RetrievalFilters(
        product_id=_u(snapshot.get("product_id")),
        version_ids=[_u(snapshot.get("product_version_id"))] if snapshot.get("product_version_id") else [],
        document_type_ids=[_u(snapshot.get("document_type_id"))] if snapshot.get("document_type_id") else [],
    )


def core_retrieve(state: dict, ctx):
    svc = ctx.retrieval_service_factory()
    question = state.get("normalized_question") or state.get("question") or ""
    operation = state.get("operation") or "ANSWER"
    with ctx.session_factory() as db:
        try:
            result = svc.retrieve(
                db,
                question,
                filters=_filters_from_snapshot(state.get("filters_snapshot") or {}),
                operation=operation,
            )
        except RetrievalError as exc:
            return {
                "_terminate": True,
                "final_status": "FAILED",
                "error_code": exc.code,
                "error_summary": exc.message[:300],
                "retrieval_queries": [question],
                "degradation_flags": dedupe_flags(
                    state.get("degradation_flags", []) + ["RETRIEVAL_UNAVAILABLE"]
                ),
            }
        except Exception:  # noqa: BLE001 未预期检索异常 → 可重试失败
            return {
                "_terminate": True,
                "final_status": "FAILED",
                "error_code": "RETRIEVAL_UNAVAILABLE",
                "error_summary": "检索服务异常",
                "retrieval_queries": [question],
                "degradation_flags": dedupe_flags(
                    state.get("degradation_flags", []) + ["RETRIEVAL_UNAVAILABLE"]
                ),
            }
    return {
        "retrieval_run_id": str(result.run_id) if result.run_id else None,
        "retrieval_queries": list(result.query_plan.query_texts),
        "evidence": [evidence_to_dict(ev) for ev in result.evidence],
        "evidence_status_raw": result.evidence_status,
        "retrieval_config_revision": result.config_revision,
        "degradation_flags": dedupe_flags(
            state.get("degradation_flags", []) + result.degradation_flags
        ),
    }
