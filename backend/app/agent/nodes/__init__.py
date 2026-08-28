"""Agent 节点（DD-21 §7.2/§7.3）。

- 每个节点只完成一种业务职责；
- 节点可用输入状态 + 替身依赖独立单测（core_fn(state, ctx) 为纯核心函数）；
- 节点进入/退出检查取消与总截止时间（check_limits）；
- 除 load_state、进度记录与 persist_result 外，节点不写业务表。
"""

from __future__ import annotations

import logging
import time

from .. import policies
from ..context import AgentRuntimeContext

logger = logging.getLogger(__name__)

# 节点名 → SSE progress_stage（DD-21 §16）
NODE_PROGRESS: dict[str, str] = {
    "build_context": "BUILDING_CONTEXT",
    "retrieve": "RETRIEVING",
    "rewrite_query": "ROUTING",
    "generate_general": "GENERATING",
    "answer_identity": "GENERATING",
    "generate_grounded": "GENERATING",
    "finalize_clarification": "GENERATING",
    "finalize_insufficient": "GENERATING",
    "validate_citations": "VALIDATING",
    "update_memory": "UPDATING_MEMORY",
    "persist_result": "PERSISTING",
}


def _set_progress(ctx: AgentRuntimeContext, answer_id, stage: str) -> None:
    """短事务更新 Answer.progress_stage（仅观测，不用于业务恢复）。"""
    from ...db.models.conversation import Answer

    try:
        with ctx.session_factory() as db:
            answer = db.get(Answer, answer_id)
            if answer is not None and answer.status not in ("SUCCEEDED", "FAILED", "CANCELED"):
                answer.progress_stage = stage
                db.commit()
    except Exception:  # noqa: BLE001 进度记录失败不阻断节点
        return


def node(name: str, *, check_limits: bool = True):
    """包装节点核心函数：进入检查 → 执行 → 记录 node_trace/进度/步数。

    check_limits=False（persist_result）为安全网：即使步数/超时/取消，
    也必须执行以收敛 Answer/AgentRun 终态。
    """

    def decorate(core_fn):
        def _log(state: dict, result: dict, duration_ms: float, ctx, *, terminated: bool = False) -> None:
            # DD-21 §17.1 结构化日志：只记 ID/节点/耗时/步数/错误码/降级，不记正文与密钥
            logger.info(
                "agent_node_finished",
                extra={
                    "run_id": state.get("run_id"),
                    "answer_id": state.get("answer_id"),
                    "conversation_id": state.get("conversation_id"),
                    "graph_version": state.get("graph_version"),
                    "node": name,
                    "operation": result.get("operation") or state.get("operation"),
                    "duration_ms": round(duration_ms, 3),
                    "step_count": result.get("step_count", state.get("step_count", 0)),
                    "model_config_id": (
                        getattr(getattr(ctx, "models", None), "last_model_key", None)
                    ),
                    "retrieval_run_id": result.get("retrieval_run_id") or state.get("retrieval_run_id"),
                    "degradation_flags": result.get("degradation_flags") or state.get("degradation_flags"),
                    "error_code": result.get("error_code") or state.get("error_code"),
                    "terminated": terminated,
                },
            )

        def wrapped(state, runtime):
            ctx = runtime.context
            if check_limits:
                limit = policies.check_limits(state, ctx)
                if limit is not None:
                    trace = list(state.get("node_trace", []))
                    trace.append(
                        {
                            "node": name,
                            "duration_ms": 0.0,
                            "operation": state.get("operation"),
                            "terminated": True,
                        }
                    )
                    limit["node_trace"] = trace
                    _log(state, limit, 0.0, ctx, terminated=True)
                    return limit
            start = time.monotonic()
            result = core_fn(state, ctx) or {}
            result = dict(result)
            result["step_count"] = state.get("step_count", 0) + 1
            trace = list(state.get("node_trace", []))
            trace.append(
                {
                    "node": name,
                    "duration_ms": round((time.monotonic() - start) * 1000, 3),
                    "operation": state.get("operation") or result.get("operation"),
                }
            )
            result["node_trace"] = trace
            _log(state, result, (time.monotonic() - start) * 1000, ctx)
            stage = NODE_PROGRESS.get(name)
            if stage and not result.get("_terminate"):
                _set_progress(ctx, state["answer_id"], stage)
            return result

        wrapped.__name__ = f"node_{name}"  # 便于观测与调试
        return wrapped

    return decorate


def dedupe_flags(flags: list[str]) -> list[str]:
    seen: list[str] = []
    for flag in flags or []:
        if flag and flag not in seen:
            seen.append(flag)
    return seen
