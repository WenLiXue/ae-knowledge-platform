"""Agent 运行时（DD-21 §7.4/§12）：invoke/resume、PostgresSaver 与 checkpoint 清理。"""

from __future__ import annotations

import logging

import psycopg_pool
from langgraph.checkpoint.postgres import PostgresSaver

from ..core.config import Settings, get_settings
from .context import AgentRuntimeContext, build_context
from .graph import build_agent_graph
from .state import AgentState

logger = logging.getLogger(__name__)

# checkpoint 独立 schema（DD-21 §11.3）
CHECKPOINT_SCHEMA = "agent_runtime"
_SEARCH_PATH = f"{CHECKPOINT_SCHEMA},conversation,knowledge,public"


def _to_psycopg_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)


def create_checkpointer(
    dsn: str | None = None, *, settings: Settings | None = None
) -> PostgresSaver:
    """创建 PostgresSaver：agent_runtime schema，autocommit 连接，幂等建表。"""
    settings = settings or get_settings()
    dsn = _to_psycopg_dsn(dsn or settings.agent_checkpoint_dsn or settings.database_url)

    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{CHECKPOINT_SCHEMA}"')

    pool = psycopg_pool.ConnectionPool(
        conninfo=dsn,
        kwargs={"options": f"-c search_path={_SEARCH_PATH}", "autocommit": True},
        open=False,
    )
    pool.open()
    saver = PostgresSaver(pool)
    saver.setup()
    return saver


# 进程级缓存的 checkpointer。setup() 会执行 CREATE INDEX CONCURRENTLY，
# 必须在本进程任何 DB 事务开放之前完成（否则会阻塞等待活跃事务）。
_saver_cache: PostgresSaver | None = None
_saver_init_failed: bool = False


def ensure_checkpoint_schema(settings: Settings | None = None) -> PostgresSaver | None:
    """初始化并缓存 PostgresSaver（幂等，进程生命周期内只 setup 一次）。

    必须在无开放 DB 事务的上下文调用：Worker 启动、应用启动或测试会话初始化。
    setup() 失败时缓存失败标记并返回 None（后续调用不再重试 setup），回答降级为
    无 checkpoint（仍可完成，仅无法恢复）。
    """
    global _saver_cache, _saver_init_failed
    if _saver_cache is not None or _saver_init_failed:
        return _saver_cache
    try:
        _saver_cache = create_checkpointer(settings=settings)
        return _saver_cache
    except Exception as exc:  # noqa: BLE001
        _saver_init_failed = True
        logger.warning("agent_checkpoint_unavailable reason=%s", str(exc)[:200])
        return None


def get_checkpointer(settings: Settings | None = None) -> PostgresSaver | None:
    """返回进程级缓存的 checkpointer（不存在则初始化）。"""
    return ensure_checkpoint_schema(settings=settings)


def create_checkpointer_or_none(settings: Settings | None = None) -> PostgresSaver | None:
    """兼容别名：返回进程级缓存的 checkpointer。"""
    return get_checkpointer(settings=settings)


def cleanup_checkpoints(
    saver: PostgresSaver,
    *,
    success_retention_days: int,
    failed_retention_days: int,
    now=None,
) -> int:
    """按 agent_runs 终态与保留期清理 checkpoint（不删除业务数据）。"""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from ..db.models.conversation import AgentRun
    from ..db.session import SessionLocal

    now = now or datetime.now(timezone.utc)
    with SessionLocal() as db:
        threads: list[str] = []
        for status, retention in (
            ("SUCCEEDED", success_retention_days),
            ("FAILED", failed_retention_days),
            ("CANCELED", failed_retention_days),
        ):
            cutoff = now - timedelta(days=retention)
            rows = db.execute(
                select(AgentRun.checkpoint_thread_id).where(
                    AgentRun.status == status, AgentRun.completed_at < cutoff
                )
            ).scalars().all()
            threads.extend(str(t) for t in rows)
        if not threads:
            return 0
        removed = 0
        for thread_id in threads:
            try:
                saver.delete_thread(thread_id)  # PostgresSaver.delete_thread(thread_id: str)
                removed += 1
            except Exception:  # noqa: BLE001 单个清理失败不阻断
                logger.warning("checkpoint_cleanup_failed thread=%s", thread_id)
        return removed


def run_agent(
    initial_state: AgentState,
    *,
    context: AgentRuntimeContext,
    checkpointer=None,
    settings: Settings | None = None,
) -> dict:
    """invoke 或 resume 图。

    - 有 checkpoint 且存在执行历史 → 以 None 输入 resume（复用计数与已完成节点）；
    - 否则全新 invoke 初始状态。
    Worker 重试必须复用同一 answer_id/thread_id，不得重置计数器。
    """
    settings = settings or context.settings
    graph = build_agent_graph(checkpointer=checkpointer)
    config = {
        "configurable": {"thread_id": str(initial_state["answer_id"])},
        # recursion_limit 留足循环余量；真实步数硬限制由 step_count 状态控制
        "recursion_limit": settings.agent_max_steps + 8,
    }
    if checkpointer is not None:
        existing = checkpointer.get_tuple(config)
        if existing is not None:
            if initial_state.get("resume_requested"):
                resumed = dict(existing.checkpoint.get("channel_values", {}))
                # A WAITING checkpoint ended at persist_result. Approval API has
                # already validated the user decision; reopen only the blocked
                # step and continue with the same bounded counters.
                if resumed.get("final_status") == "WAITING":
                    resumed["_terminate"] = False
                    resumed["final_status"] = None
                    resumed["suspended_reason"] = None
                    for step in resumed.get("plan_steps", []):
                        if step.get("status") == "WAITING_APPROVAL":
                            step["status"] = "PENDING"
                result = graph.invoke(resumed, config=config, context=context)
            else:
                result = graph.invoke(None, config=config, context=context)
        else:
            result = graph.invoke(initial_state, config=config, context=context)
    else:
        result = graph.invoke(initial_state, config=config, context=context)
    return result


def build_runtime_for_worker(
    *,
    settings: Settings | None = None,
    session_factory=None,
    retrieval_service_factory=None,
    models=None,
    clock=None,
    deadline=None,
) -> AgentRuntimeContext:
    """Worker 适配器使用的便捷构建入口。"""
    from .context import AgentModels

    if models is None and session_factory is not None:
        models = AgentModels(session_factory=session_factory)
    return build_context(
        settings=settings,
        session_factory=session_factory,
        retrieval_service_factory=retrieval_service_factory,
        models=models,
        clock=clock,
        deadline=deadline,
    )
