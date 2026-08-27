"""Safe, bounded execution for registered tools."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from ..contracts.tool import ToolCallProposal, ToolResultEnvelope
from .base import ToolContext, ToolError
from .policy import ToolPolicy
from .registry import ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, *, policy: ToolPolicy | None = None) -> None:
        self.registry = registry
        self.policy = policy or ToolPolicy()

    def execute(
        self,
        proposal: ToolCallProposal,
        context: ToolContext,
        *,
        confirmed: bool = False,
    ) -> ToolResultEnvelope:
        started = datetime.now(timezone.utc)
        try:
            tool = self.registry.get(proposal.tool_name)
            definition = tool.definition
            self.policy.authorize(definition, context, confirmed=confirmed)
            args = tool.input_model.model_validate(proposal.arguments)
            # Tool code is synchronous today; elapsed time is still bounded at the
            # executor contract so async/isolated execution can be added later.
            begin = time.monotonic()
            tool_context = replace(
                context,
                metadata={**context.metadata, "call_id": proposal.call_id},
            )
            result = tool.execute(args, tool_context)
            if time.monotonic() - begin > definition.timeout_seconds:
                raise ToolError("TOOL_TIMEOUT", "工具执行超过时间限制", retryable=True)
            return self._bounded(result, definition.max_result_bytes)
        except ValidationError as exc:
            return self._failure(proposal, locals().get("definition", _unknown_version()), "TOOL_INPUT_INVALID", "工具参数校验失败", False, started)
        except ToolError as exc:
            return self._failure(proposal, locals().get("definition", _unknown_version()), exc.code, exc.message, exc.retryable, started)
        except Exception:
            return self._failure(proposal, locals().get("definition", _unknown_version()), "TOOL_EXECUTION_FAILED", "工具执行失败", False, started)

    @staticmethod
    def _bounded(result: ToolResultEnvelope, max_bytes: int) -> ToolResultEnvelope:
        payload = json.dumps(result.data, ensure_ascii=False, default=str).encode("utf-8")
        if len(payload) <= max_bytes:
            return result
        data = dict(result.data or {})
        data["_truncated"] = True
        return result.model_copy(update={"data": {"summary": result.summary, "data": data}, "truncated": True})

    @staticmethod
    def _failure(proposal, version: str, code: str, message: str, retryable: bool, started) -> ToolResultEnvelope:
        return ToolResultEnvelope(
            call_id=proposal.call_id,
            tool_name=proposal.tool_name,
            tool_version=version,
            status="FAILED",
            summary=message,
            error_code=code,
            retryable=retryable,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
        )


def new_call_id() -> str:
    return str(uuid.uuid4())


def _unknown_version() -> str:
    return "0.0"
