"""load_state：加载 Answer/Conversation/Message/过滤器；检查所有权、终态与取消；创建/更新 AgentRun。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from ...db.models.conversation import AgentRun, Answer, Conversation, Message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def core_load_state(state: dict, ctx):
    with ctx.session_factory() as db:
        answer = db.get(Answer, uuid.UUID(str(state["answer_id"])))
        if answer is None:
            return {
                "_terminate": True,
                "final_status": "FAILED",
                "error_code": "ANSWER_NOT_FOUND",
                "error_summary": "答案不存在",
            }
        if state.get("user_id") and str(answer.user_id) != str(state["user_id"]):
            return {
                "_terminate": True,
                "final_status": "FAILED",
                "error_code": "AGENT_INPUT_INVALID",
                "error_summary": "无权访问该答案",
            }
        conversation = db.get(Conversation, answer.conversation_id)
        message = db.get(Message, answer.message_id)
        question = message.content if message is not None else answer.summary or ""

        # 已终态 → 幂等：不再执行图，直接进入 persist_result 收敛
        if answer.status in ("SUCCEEDED", "FAILED", "CANCELED"):
            return {
                "question": question,
                "current_message_id": str(answer.message_id),
                "conversation_id": str(answer.conversation_id),
                "user_id": str(answer.user_id),
                "filters_snapshot": conversation.filters_snapshot if conversation else {},
                "final_status": answer.status,
                "cancel_requested": answer.status == "CANCELED",
            }

        if answer.cancel_requested:
            return {
                "question": question,
                "current_message_id": str(answer.message_id),
                "conversation_id": str(answer.conversation_id),
                "user_id": str(answer.user_id),
                "filters_snapshot": conversation.filters_snapshot if conversation else {},
                "_terminate": True,
                "final_status": "CANCELED",
                "error_code": "AGENT_CANCELED",
                "error_summary": "用户已取消回答",
            }

        # 创建或更新 AgentRun
        run = db.execute(
            select(AgentRun).where(AgentRun.answer_id == answer.id)
        ).scalars().first()
        if run is None:
            run = AgentRun(
                answer_id=answer.id,
                conversation_id=answer.conversation_id,
                status="RUNNING",
                graph_version=state["graph_version"],
                checkpoint_thread_id=str(answer.id),
                max_steps=ctx.settings.agent_max_steps,
                degradation_flags=[],
                step_count=0,
            )
            db.add(run)
        else:
            run.status = "RUNNING"
            run.graph_version = state["graph_version"]
        run.started_at = run.started_at or _now()
        db.commit()

        return {
            "question": question,
            "current_message_id": str(answer.message_id),
            "conversation_id": str(answer.conversation_id),
            "user_id": str(answer.user_id),
            "filters_snapshot": conversation.filters_snapshot if conversation else {},
            "cancel_requested": False,
            "operation": "",
        }
