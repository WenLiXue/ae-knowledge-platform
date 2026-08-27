"""Confirmation contract for side-effecting tools."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .tools.base import ToolError


def arguments_hash(arguments: dict) -> str:
    return hashlib.sha256(json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def create_approval(session_factory, *, state: dict, step_id: str, tool_name: str, arguments: dict, impact_summary: dict, ttl_minutes: int = 30) -> str:
    from ..db.models.conversation import AgentApproval, AgentPlan, AgentPlanStep, AgentRun

    plan_id = state.get("plan_id")
    if not plan_id:
        raise ToolError("APPROVAL_INVALID", "确认缺少计划")
    with session_factory() as db:
        run = db.execute(select(AgentRun).where(AgentRun.answer_id == uuid.UUID(str(state["answer_id"])))).scalar_one_or_none()
        plan = db.get(AgentPlan, uuid.UUID(str(plan_id)))
        step = db.execute(select(AgentPlanStep).where(AgentPlanStep.plan_id == plan.id, AgentPlanStep.step_key == step_id)).scalar_one_or_none() if plan else None
        if run is None or plan is None or step is None:
            raise ToolError("APPROVAL_INVALID", "确认对象不存在")
        approval = AgentApproval(
            run_id=run.id,
            plan_id=plan.id,
            step_id=step.id,
            requested_by=uuid.UUID(str(state["user_id"])),
            status="PENDING",
            tool_name=tool_name,
            arguments_hash=arguments_hash(arguments),
            impact_summary=impact_summary,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
        )
        step.status = "WAITING_APPROVAL"
        if plan.status == "DRAFT":
            plan.status = "WAITING"
        db.add(approval)
        db.commit()
        return str(approval.id)


def verify_approval(session_factory, *, approval_id: str, user_id: str, plan_id: str, tool_name: str, arguments: dict) -> bool:
    from ..db.models.conversation import AgentApproval

    with session_factory() as db:
        approval = db.get(AgentApproval, uuid.UUID(str(approval_id)))
        if approval is None or str(approval.requested_by) != str(user_id):
            raise ToolError("APPROVAL_INVALID", "确认不存在或不属于当前用户")
        if approval.status != "APPROVED":
            raise ToolError("APPROVAL_REQUIRED", "工具尚未获得确认")
        if approval.plan_id != uuid.UUID(str(plan_id)) or approval.tool_name != tool_name:
            raise ToolError("APPROVAL_STALE", "计划或工具已变化，需要重新确认")
        if approval.expires_at <= datetime.now(timezone.utc):
            raise ToolError("APPROVAL_EXPIRED", "确认已过期")
        if approval.arguments_hash != arguments_hash(arguments):
            raise ToolError("APPROVAL_STALE", "执行参数已变化，需要重新确认")
        return True


def decide_approval(session_factory, *, approval_id: str, user_id: str, decision: str) -> dict:
    """Atomically decide an approval and enqueue one resumable Agent run."""
    from ..db.models.conversation import AgentApproval, AgentPlan, AgentRun, Answer
    from ..db.models.task import ProcessingTask

    if decision not in {"APPROVED", "REJECTED"}:
        raise ToolError("APPROVAL_DECISION_INVALID", "确认决策无效")
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        approval = db.execute(
            select(AgentApproval).where(AgentApproval.id == uuid.UUID(str(approval_id))).with_for_update()
        ).scalar_one_or_none()
        if approval is None or str(approval.requested_by) != str(user_id):
            raise ToolError("APPROVAL_INVALID", "确认不存在或不属于当前用户")
        if approval.status != "PENDING":
            raise ToolError("APPROVAL_ALREADY_DECIDED", "确认已经处理过")
        if approval.expires_at <= now:
            approval.status = "EXPIRED"
            db.commit()
            raise ToolError("APPROVAL_EXPIRED", "确认已过期")

        run = db.get(AgentRun, approval.run_id)
        answer = db.get(Answer, run.answer_id) if run else None
        if run is None or answer is None:
            raise ToolError("APPROVAL_INVALID", "关联的 Agent 运行不存在")
        approval.status = decision
        approval.decision_by = uuid.UUID(str(user_id))
        approval.decided_at = now
        plan = db.get(AgentPlan, approval.plan_id)
        if decision == "REJECTED":
            answer.status = "FAILED"
            answer.progress_stage = None
            answer.error_code = "APPROVAL_REJECTED"
            answer.error_summary = "用户拒绝执行该操作"
            answer.completed_at = now
            run.status = "FAILED"
            run.error_code = "APPROVAL_REJECTED"
            run.error_summary = "用户拒绝执行该操作"
            run.completed_at = now
            if plan:
                plan.status = "CANCELED"
        else:
            answer.status = "PENDING"
            answer.progress_stage = "RESUMING"
            run.status = "RUNNING"
            if plan:
                plan.status = "RUNNING"
            task_key = f"answer:{answer.id}:stage:generate_answer"
            open_task = db.execute(
                select(ProcessingTask).where(
                    ProcessingTask.idempotency_key == task_key,
                    ProcessingTask.status.in_(("PENDING", "RUNNING", "RETRY_WAIT")),
                )
            ).scalar_one_or_none()
            if open_task is None:
                db.add(ProcessingTask(
                    task_type="GENERATE_ANSWER",
                    status="PENDING",
                    idempotency_key=task_key,
                    scheduled_at=now,
                    payload={"answer_id": str(answer.id)},
                    priority=50,
                    max_attempts=3,
                    created_by_user_id=uuid.UUID(str(user_id)),
                ))
        db.commit()
        return {"approval_id": str(approval.id), "status": decision, "answer_id": str(answer.id)}
