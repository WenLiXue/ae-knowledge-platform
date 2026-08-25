"""基于数据库任务表的 Worker。

领取（DD-03 §9.3）、租约与心跳（§9.4）、重试（DD-02 §8）、attempt 记录（DD-03 §6.2）：

- claim：`FOR UPDATE SKIP LOCKED` 领取 PENDING/RETRY_WAIT 且到期的任务；回收租约过期的 RUNNING 任务；
- 执行：单任务独立事务，不持有领取事务；成功创建下一阶段任务；
- 失败：TRANSIENT 可重试（指数退避）→ 耗尽后 FAILED；不可重试错误立即 FAILED；来源下线 → CANCELED；
- attempt：每次领取记录 task_attempts，完成时回填结果与错误。

测试与演示：`WorkerRunner.claim_and_execute()` 执行一个轮询周期；独立进程用 `python -m app.worker` 持续轮询。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.context import TaskContext, reset_task_context, set_service, set_task_context
from ..core.logging import setup_logging
from ..db.models.knowledge import DocumentVersion, KnowledgeSource
from ..db.models.task import ProcessingTask, TaskAttempt
from ..db.session import SessionLocal
from ..feishu_auth.base import FeishuOAuthClient
from ..feishu_auth.factory import get_feishu_oauth_client
from ..feishu_provider.base import FeishuDocumentProvider
from ..feishu_provider.factory import get_feishu_provider
from ..search.factory import get_search_adapter
from ..storage.local import LocalObjectStore
from . import pipeline

logger = logging.getLogger(__name__)

_CLAIMABLE_STATUSES = ("PENDING", "RETRY_WAIT")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WorkerRunner:
    def __init__(
        self,
        *,
        session_factory=None,
        worker_id: str | None = None,
        lease_seconds: int | None = None,
        retry_base_delay_seconds: float | None = None,
        batch_size: int | None = None,
        provider: FeishuDocumentProvider | None = None,
        oauth_client: FeishuOAuthClient | None = None,
        store=None,
        search=None,
    ):
        settings = get_settings()
        self.session_factory = session_factory or SessionLocal
        self.worker_id = worker_id or settings.worker_id
        self.lease_seconds = (
            lease_seconds if lease_seconds is not None else settings.lease_seconds
        )
        self.retry_base_delay = (
            retry_base_delay_seconds
            if retry_base_delay_seconds is not None
            else settings.retry_base_delay_seconds
        )
        self.batch_size = batch_size or settings.worker_batch_size
        # 文档读取走适配器；Fake/Real 由配置决定，Worker 不直接依赖飞书 SDK
        self.provider = provider or get_feishu_provider(settings)
        self.oauth_client = oauth_client or get_feishu_oauth_client(settings)
        self.store = store or LocalObjectStore(settings.storage_root)
        self.search = search or get_search_adapter(settings)

    def claim_and_execute(self, batch_size: int | None = None) -> list[str]:
        """执行一个轮询周期：领取一批任务并逐个执行，返回每个任务的执行结果。"""
        batch = batch_size or self.batch_size
        claimed = self._claim(batch)
        outcomes: list[str] = []
        for task in claimed:
            outcomes.append(self._execute(task))
        return outcomes

    def _claim(self, batch_size: int) -> list[ProcessingTask]:
        session = self.session_factory()
        try:
            with session.begin():
                now = _now()
                picked_ids = session.execute(
                    select(ProcessingTask.id)
                    .where(
                        or_(
                            and_(
                                ProcessingTask.status.in_(_CLAIMABLE_STATUSES),
                                ProcessingTask.scheduled_at <= now,
                            ),
                            and_(
                                ProcessingTask.status == "RUNNING",
                                ProcessingTask.lease_expires_at <= now,
                            ),
                        )
                    )
                    .order_by(
                        ProcessingTask.priority,
                        ProcessingTask.scheduled_at,
                        ProcessingTask.created_at,
                        ProcessingTask.id,
                    )
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                ).scalars().all()
                if not picked_ids:
                    return []

                rows = session.execute(
                    select(ProcessingTask)
                    .where(ProcessingTask.id.in_(picked_ids))
                    .with_for_update()
                ).scalars().all()

                for task in rows:
                    if task.status == "RUNNING":
                        # 回收租约过期的任务：标记旧 attempt 为 ABANDONED
                        session.execute(
                            update(TaskAttempt)
                            .where(
                                TaskAttempt.task_id == task.id,
                                TaskAttempt.result.is_(None),
                            )
                            .values(result="ABANDONED", finished_at=now)
                        )
                    task.status = "RUNNING"
                    task.lease_owner = self.worker_id
                    task.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
                    task.heartbeat_at = now
                    task.attempt_count += 1
                    session.add(
                        TaskAttempt(
                            task_id=task.id,
                            attempt_no=task.attempt_count,
                            worker_id=self.worker_id,
                            started_at=now,
                        )
                    )
                    logger.info("task_claimed", extra={"task_id": str(task.id)})
                return rows
        finally:
            session.close()

    def _execute(self, task: ProcessingTask) -> str:
        """执行单个已领取任务（独立事务）。"""
        session = self.session_factory()
        attempt_no = task.attempt_count
        ctx_token = set_task_context(
            TaskContext(
                task_id=str(task.id),
                attempt_no=attempt_no,
                task_type=task.task_type,
                source_id=str(task.source_id) if task.source_id else None,
                version_id=str(task.version_id) if task.version_id else None,
                worker_id=self.worker_id,
            )
        )
        try:
            with session.begin():
                locked = session.execute(
                    select(ProcessingTask)
                    .where(ProcessingTask.id == task.id)
                    .with_for_update()
                ).scalar_one()
                if locked.status != "RUNNING" or locked.lease_owner != self.worker_id:
                    # 租约已被回收或转交，放弃本次 attempt
                    self._record_attempt(session, task.id, attempt_no, "ABANDONED", None, None)
                    return "ABANDONED"

                try:
                    next_type = pipeline.execute_stage(
                        session,
                        locked,
                        provider=self.provider,
                        oauth_client=self.oauth_client,
                        store=self.store,
                        search=self.search,
                    )
                except pipeline.PipelineError as exc:
                    return self._handle_failure(session, locked, exc)

                locked.status = "SUCCEEDED"
                locked.last_error_category = None
                locked.last_error_code = None
                locked.last_error_summary = None
                if next_type:
                    self._create_next_task(session, locked, next_type)
                self._record_attempt(session, locked.id, attempt_no, "SUCCEEDED", None, None)
                return "SUCCEEDED"
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            return self._handle_unexpected_error(task, exc)
        finally:
            reset_task_context(ctx_token)
            session.close()

    def _handle_failure(self, session: Session, task: ProcessingTask, exc: pipeline.PipelineError) -> str:
        task.last_error_category = exc.category
        task.last_error_code = exc.code
        task.last_error_summary = exc.message[:500]
        if exc.retryable and task.attempt_count < task.max_attempts:
            task.status = "RETRY_WAIT"
            task.scheduled_at = self._next_retry_at(task.attempt_count)
            self._record_attempt(session, task.id, task.attempt_count, "FAILED", exc.category, exc.code)
            logger.warning(
                "task_retry_scheduled",
                extra={
                    "category": exc.category,
                    "code": exc.code,
                    "attempt": task.attempt_count,
                    "max_attempts": task.max_attempts,
                    "error_summary": exc.message[:200],
                },
            )
            return "RETRY_WAIT"
        task.status = "FAILED"
        self._mark_version_source_failed(session, task, exc)
        self._record_attempt(session, task.id, task.attempt_count, "FAILED", exc.category, exc.code)
        logger.error(
            "task_failed",
            extra={"category": exc.category, "code": exc.code, "error_summary": exc.message[:500]},
        )
        return "FAILED"

    def _handle_unexpected_error(self, task: ProcessingTask, exc: Exception) -> str:
        """未预期异常按 INTERNAL 可重试错误处理（回滚后重排）。"""
        logger.error("task_unexpected_error", exc_info=exc)
        session = self.session_factory()
        try:
            with session.begin():
                locked = session.execute(
                    select(ProcessingTask)
                    .where(ProcessingTask.id == task.id)
                    .with_for_update()
                ).scalar_one()
                if locked.status == "RUNNING" and locked.lease_owner == self.worker_id:
                    return self._handle_failure(
                        session,
                        locked,
                        pipeline.PipelineError(
                            "INTERNAL", "INTERNAL_ERROR", f"未预期异常: {exc!r}", retryable=True
                        ),
                    )
                return "ABANDONED"
        finally:
            session.close()

    def _mark_version_source_failed(self, session: Session, task: ProcessingTask, exc) -> None:
        version = session.get(DocumentVersion, task.version_id)
        if version is not None and version.status in ("PROCESSING", "PENDING_CONFIRMATION"):
            version.status = "FAILED"
            version.error_code = exc.code
            version.error_summary = exc.message[:500]
        source = session.get(KnowledgeSource, task.source_id)
        if source is not None and source.status == "PROCESSING":
            source.status = "FAILED"

    def _record_attempt(
        self,
        session: Session,
        task_id,
        attempt_no: int,
        result: str | None,
        category: str | None,
        code: str | None,
    ) -> None:
        if attempt_no is None:
            return
        attempt = session.execute(
            select(TaskAttempt)
            .where(
                TaskAttempt.task_id == task_id,
                TaskAttempt.attempt_no == attempt_no,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if attempt is None:
            return
        attempt.result = result
        attempt.finished_at = _now()
        attempt.error_category = category
        attempt.error_code = code

    def _create_next_task(self, session: Session, task: ProcessingTask, next_type: str) -> None:
        if task.version_id is None:
            return
        key = f"version:{task.version_id}:stage:{next_type.lower()}"
        existing = session.execute(
            select(ProcessingTask).where(
                ProcessingTask.idempotency_key == key,
                ProcessingTask.status.in_(("PENDING", "RUNNING", "RETRY_WAIT")),
            )
        ).scalars().first()
        if existing:
            return
        session.add(
            ProcessingTask(
                task_type=next_type,
                status="PENDING",
                idempotency_key=key,
                # 显式 Python 时钟，与领取比较时钟一致（避免 DB/Python 时钟漂移）
                scheduled_at=_now(),
                source_id=task.source_id,
                version_id=task.version_id,
                parent_task_id=task.id,
                payload=task.payload,
                priority=task.priority,
                max_attempts=task.max_attempts,
                created_by_user_id=task.created_by_user_id,
            )
        )

    def _next_retry_at(self, attempt: int) -> datetime:
        delay = self.retry_base_delay * (2 ** (attempt - 1))
        return _now() + timedelta(seconds=delay)

    def heartbeat(self, task_id, worker_id: str | None = None) -> bool:
        """续租：仅 RUNNING 且租约持有者本人可续。返回是否成功。"""
        owner = worker_id or self.worker_id
        session = self.session_factory()
        try:
            with session.begin():
                task = session.execute(
                    select(ProcessingTask).where(ProcessingTask.id == task_id).with_for_update()
                ).scalar_one_or_none()
                if task is None or task.status != "RUNNING" or task.lease_owner != owner:
                    return False
                task.lease_expires_at = _now() + timedelta(seconds=self.lease_seconds)
                task.heartbeat_at = _now()
                return True
        finally:
            session.close()

    def run_forever(self, poll_interval: float | None = None) -> None:
        interval = (
            poll_interval if poll_interval is not None else get_settings().worker_poll_interval_seconds
        )
        logger.info("Worker %s 启动，轮询间隔 %.1fs", self.worker_id, interval)
        while True:
            try:
                self.claim_and_execute()
            except Exception:  # noqa: BLE001
                logger.exception("Worker 轮询异常，进入下一轮")
            time.sleep(interval)


def main() -> None:
    setup_logging()
    set_service("worker")
    WorkerRunner().run_forever()


if __name__ == "__main__":
    main()
