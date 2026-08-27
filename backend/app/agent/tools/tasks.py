"""Low-risk tasking tools exposed through the Agent policy boundary."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select

from ...db.models.task import ProcessingTask
from ..contracts.tool import ToolDefinition, ToolResultEnvelope
from .base import ToolContext, ToolError


class TaskRetryInput(BaseModel):
    task_id: uuid.UUID


class TaskRetryOutput(BaseModel):
    task_id: uuid.UUID
    status: Literal["PENDING", "ALREADY_QUEUED"]


class TaskRetryTool:
    input_model = TaskRetryInput
    output_model = TaskRetryOutput
    definition = ToolDefinition(
        name="task.retry",
        version="1.0",
        description="重新排队一个失败的后台处理任务。",
        input_schema=TaskRetryInput.model_json_schema(),
        output_schema=TaskRetryOutput.model_json_schema(),
        risk="LOW_RISK_WRITE",
        side_effect=True,
        requires_confirmation=True,
        idempotency="REQUIRED",
        required_permissions=["task:write"],
        timeout_seconds=10,
        max_retries=0,
        sensitivity="INTERNAL",
    )

    def execute(self, args: TaskRetryInput, context: ToolContext) -> ToolResultEnvelope:
        if context.session_factory is None:
            raise ToolError("TOOL_CONTEXT_INVALID", "任务工具缺少数据库会话工厂")
        with context.session_factory() as db:
            task = db.execute(
                select(ProcessingTask).where(ProcessingTask.id == args.task_id).with_for_update()
            ).scalar_one_or_none()
            if task is None:
                raise ToolError("TASK_NOT_FOUND", "任务不存在")
            if task.created_by_user_id and str(task.created_by_user_id) != str(context.user_id):
                raise ToolError("TOOL_PERMISSION_DENIED", "无权重试该任务")
            if task.status in ("PENDING", "RUNNING", "RETRY_WAIT"):
                output = TaskRetryOutput(task_id=task.id, status="ALREADY_QUEUED")
            elif task.status == "FAILED":
                task.status = "PENDING"
                task.scheduled_at = datetime.now(timezone.utc)
                task.attempt_count = 0
                task.last_error_category = None
                task.last_error_code = None
                task.last_error_summary = None
                output = TaskRetryOutput(task_id=task.id, status="PENDING")
            else:
                raise ToolError("TASK_NOT_RETRYABLE", "当前任务状态不允许重试")
            db.commit()
        now = datetime.now(timezone.utc)
        return ToolResultEnvelope(
            call_id=str(context.metadata.get("call_id") or uuid.uuid4()),
            tool_name=self.definition.name,
            tool_version=self.definition.version,
            status="SUCCEEDED",
            data=output.model_dump(mode="json"),
            summary="任务已重新排队" if output.status == "PENDING" else "任务已经在队列中",
            sensitivity=self.definition.sensitivity,
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )


def register_task_tools(registry) -> None:
    registry.register(TaskRetryTool())
