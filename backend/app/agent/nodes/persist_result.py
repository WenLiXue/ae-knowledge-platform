"""persist_result：原子写 Answer + AnswerCitation + AgentRun；幂等；远程调用不在事务内。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select

from ...db.models.conversation import AgentRun, Answer, AnswerCitation
from . import dedupe_flags


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _finalize_run(
    db,
    state: dict,
    answer: Answer,
    run: AgentRun | None,
    status: str,
    *,
    error_code=None,
    error_summary=None,
) -> None:
    if run is None:
        return
    run.status = status
    run.operation = state.get("operation") or run.operation
    run.step_count = state.get("step_count", 0)
    run.degradation_flags = dedupe_flags(state.get("degradation_flags") or [])
    trace = state.get("node_trace") or []
    if trace:
        run.current_node = str(trace[-1].get("node"))
        run.timings = {"nodes": {t.get("node"): t.get("duration_ms") for t in trace}, "count": len(trace)}
    run.error_code = error_code
    run.error_summary = (error_summary or "")[:500]
    run.completed_at = _now()


def core_persist_result(state: dict, ctx):
    final_status = state.get("final_status") or "SUCCEEDED"
    error_code = state.get("error_code")
    error_summary = state.get("error_summary")

    with ctx.session_factory() as db:
        answer = db.execute(
            select(Answer).where(Answer.id == uuid.UUID(str(state["answer_id"]))).with_for_update()
        ).scalar_one_or_none()
        if answer is None:
            return {"final_status": "FAILED", "error_code": "ANSWER_NOT_FOUND", "error_summary": "答案不存在"}
        run = db.execute(
            select(AgentRun).where(AgentRun.answer_id == answer.id)
        ).scalars().first()

        # 幂等：已终态直接收敛（不重复写）
        if answer.status in ("SUCCEEDED", "FAILED", "CANCELED"):
            _finalize_run(db, state, answer, run, answer.status)
            db.commit()
            return {
                "final_status": answer.status,
                "error_code": answer.error_code,
                "error_summary": answer.error_summary,
            }

        # 取消优先（DD-21 §9：用户取消后不能继续发布答案）
        if answer.cancel_requested or state.get("cancel_requested"):
            answer.status = "CANCELED"
            answer.progress_stage = None
            answer.completed_at = _now()
            _finalize_run(db, state, answer, run, "CANCELED", error_code="AGENT_CANCELED")
            db.commit()
            return {"final_status": "CANCELED"}

        if final_status == "FAILED":
            answer.status = "FAILED"
            answer.progress_stage = None
            answer.error_code = error_code
            answer.error_summary = (error_summary or "")[:500]
            answer.completed_at = _now()
            _finalize_run(db, state, answer, run, "FAILED", error_code=error_code, error_summary=error_summary)
            db.commit()
            return {"final_status": "FAILED", "error_code": error_code}

        if final_status == "CANCELED":
            answer.status = "CANCELED"
            answer.progress_stage = None
            answer.completed_at = _now()
            _finalize_run(db, state, answer, run, "CANCELED", error_code=error_code or "AGENT_CANCELED")
            db.commit()
            return {"final_status": "CANCELED"}

        if final_status == "WAITING":
            answer.status = "WAITING"
            answer.progress_stage = state.get("suspended_reason") or "WAITING_APPROVAL"
            answer.error_code = None
            answer.error_summary = None
            if run is not None:
                _finalize_run(db, state, answer, run, "WAITING")
                run.completed_at = None
            db.commit()
            return {"final_status": "WAITING", "pending_approval_id": state.get("pending_approval_id")}

        # SUCCEEDED：答案 + 引用 + AgentRun 原子写
        answer.status = "SUCCEEDED"
        answer.progress_stage = None
        answer.answer_type = state.get("answer_type")
        answer.summary = state.get("answer_summary")
        answer.blocks_json = state.get("answer_blocks") or []
        answer.degradation_flags = dedupe_flags(state.get("degradation_flags") or [])
        if state.get("retrieval_run_id"):
            answer.retrieval_run_id = uuid.UUID(str(state["retrieval_run_id"]))
        answer.retrieval_config_revision = state.get("retrieval_config_revision")
        answer.model_key = state.get("model_key")
        answer.error_code = None
        answer.error_summary = None
        answer.completed_at = _now()

        # 幂等引用：删除未发布引用再插入（同一 run 重复执行不产生重复引用）
        db.execute(delete(AnswerCitation).where(AnswerCitation.answer_id == answer.id))
        for draft in state.get("citation_drafts") or []:
            row = AnswerCitation(answer_id=answer.id)
            for key, value in draft.items():
                setattr(row, key, value)
            db.add(row)

        _finalize_run(db, state, answer, run, "SUCCEEDED")
        db.commit()
        return {"final_status": "SUCCEEDED"}
