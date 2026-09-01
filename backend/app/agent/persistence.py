"""Short-transaction persistence for tool-agent execution metadata."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .contracts.plan import AgentPlan
from .contracts.tool import ToolCallProposal, ToolResultEnvelope
from .tools.base import ToolError


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def persist_plan(session_factory, *, answer_id: str, plan: AgentPlan) -> None:
    from .db_models import AgentPlan as DbPlan, AgentPlanStep, AgentRun
    from ..db.models.conversation import Answer

    with session_factory() as db:
        run = db.execute(select(AgentRun).where(AgentRun.answer_id == uuid.UUID(str(answer_id)))).scalar_one_or_none()
        if run is None:
            # A retry or a worker crash can leave the Answer without its
            # runtime row. Recreate the row transactionally instead of
            # discarding an otherwise valid plan.
            answer = db.get(Answer, uuid.UUID(str(answer_id)))
            if answer is None:
                raise ToolError("AGENT_RUN_NOT_FOUND", "Agent 运行记录不存在")
            run = AgentRun(
                answer_id=answer.id,
                conversation_id=answer.conversation_id,
                status="RUNNING",
                graph_version="knowledge-assistant-v1",
                checkpoint_thread_id=str(answer.id),
                max_steps=12,
                degradation_flags=[],
                step_count=0,
            )
            db.add(run)
            db.flush()
        # A resumed checkpoint can re-enter create_plan after a lease recovery,
        # and two workers may briefly race on the same `(run_id, revision)`.
        # Treat that key as idempotent: the first committed plan is authoritative
        # and the retry must not turn a recoverable task into a terminal failure.
        existing_revision = db.execute(
            select(DbPlan).where(
                DbPlan.run_id == run.id,
                DbPlan.revision == plan.revision,
            )
        ).scalar_one_or_none()
        if existing_revision is not None:
            db.commit()
            return

        db_plan = db.get(DbPlan, uuid.UUID(str(plan.id)))
        if db_plan is None:
            db_plan = DbPlan(
                id=uuid.UUID(str(plan.id)),
                run_id=run.id,
                revision=plan.revision,
                goal=plan.goal,
                status=plan.status,
                completion_criteria=[item.model_dump(mode="json") for item in plan.completion_criteria],
            )
            db.add(db_plan)
            for sequence, step in enumerate(plan.steps, start=1):
                db.add(AgentPlanStep(
                    plan_id=db_plan.id,
                    step_key=step.id,
                    sequence=sequence,
                    title=step.title,
                    capability=step.capability,
                    dependencies=step.depends_on,
                    risk=step.risk,
                    status=step.status,
                    input_summary={"keys": sorted(step.input_bindings)},
                ))
        try:
            db.commit()
        except IntegrityError:
            # Another worker may have committed the same revision between the
            # read and insert.  Roll back and verify the idempotent row exists;
            # re-raise only for an unrelated integrity violation.
            db.rollback()
            raced = db.execute(
                select(DbPlan.id).where(
                    DbPlan.run_id == run.id,
                    DbPlan.revision == plan.revision,
                )
            ).scalar_one_or_none()
            if raced is None:
                raise


def persist_tool_call(session_factory, *, state: dict, proposal: ToolCallProposal, result: ToolResultEnvelope) -> None:
    from .db_models import AgentPlan, AgentPlanStep, AgentRun, AgentToolCall

    plan_id = state.get("plan_id")
    step_key = state.get("active_step_id")
    if not plan_id or not step_key:
        return
    with session_factory() as db:
        run = db.execute(select(AgentRun).where(AgentRun.answer_id == uuid.UUID(str(state["answer_id"])))).scalar_one_or_none()
        plan = db.get(AgentPlan, uuid.UUID(str(plan_id)))
        step = db.execute(
            select(AgentPlanStep).where(AgentPlanStep.plan_id == uuid.UUID(str(plan_id)), AgentPlanStep.step_key == step_key)
        ).scalar_one_or_none()
        if run is None or plan is None or step is None:
            return
        step.status = "SUCCEEDED" if result.status == "SUCCEEDED" else "FAILED"
        step.output_summary = {"summary": result.summary, "status": result.status, "error_code": result.error_code}
        step.error_code = result.error_code
        step.completed_at = datetime.now(timezone.utc)
        db.add(AgentToolCall(
            run_id=run.id,
            plan_id=plan.id,
            step_id=step.id,
            tool_name=result.tool_name,
            tool_version=result.tool_version,
            attempt=1,
            status=result.status,
            idempotency_key_hash=_hash({"run": str(run.id), "plan": str(plan.id), "step": step_key, "tool": result.tool_name}),
            arguments_summary={"keys": sorted(proposal.arguments)},
            result_summary={"summary": result.summary, "status": result.status, "evidence_refs": result.evidence_refs},
            error_code=result.error_code,
            retryable=result.retryable,
        ))
        db.commit()
