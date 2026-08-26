"""assess_evidence：本地规则为主，输出 SUFFICIENT/PARTIAL/CONFLICTING/INSUFFICIENT/UNAVAILABLE。"""

from __future__ import annotations

from ..policies import assess_evidence as assess_quality
from ..state import EVIDENCE_UNAVAILABLE


def core_assess_evidence(state: dict, ctx):
    quality = assess_quality(
        state.get("evidence") or [],
        state.get("evidence_status_raw") or "SUFFICIENT",
        state.get("degradation_flags") or [],
    )
    update = {"evidence_quality": quality}
    if quality == EVIDENCE_UNAVAILABLE:
        update.update(
            {
                "_terminate": True,
                "final_status": "FAILED",
                "error_code": "RETRIEVAL_UNAVAILABLE",
                "error_summary": "检索服务暂不可用，请稍后重试",
            }
        )
    return update
