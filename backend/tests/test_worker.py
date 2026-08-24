"""任务 Worker 与 Mock 文档处理流水线的集成测试。

覆盖：正常推进到 QUERYABLE、瞬时失败重试恢复、不可重试立即 FAILED、
重试耗尽 FAILED、分类 UNCERTAIN/IRRELEVANT 分支、租约过期回收、
失败来源重试后由 Worker 推进成功、心跳续租。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import SessionLocal
from app.main import app
from app.worker.runner import WorkerRunner


client = TestClient(app)


def _submit(token: str, client_item_id: str = "row-1") -> dict:
    response = client.post(
        "/api/v1/feishu/documents/submit",
        json={
            "items": [
                {
                    "client_item_id": client_item_id,
                    "resource_token": token,
                    "resource_type": "wiki",
                }
            ]
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]["items"][0]


def _runner() -> WorkerRunner:
    # retry_base_delay=0：重试立即可被下一轮领取，保证测试确定性
    return WorkerRunner(worker_id="test-worker", retry_base_delay_seconds=0.0, lease_seconds=60)


def _drain(runner: WorkerRunner, max_cycles: int = 30) -> None:
    for _ in range(max_cycles):
        if not runner.claim_and_execute(batch_size=10):
            return
    raise AssertionError("Worker 未在预期轮次内排空任务")


def _scalar(sql: str, **params):
    with SessionLocal() as session:
        return session.execute(text(sql), params).scalar_one()


def _task_chain(source_id: str) -> list[tuple[str, str, int]]:
    with SessionLocal() as session:
        rows = session.execute(
            text(
                "SELECT task_type, status, attempt_count FROM tasking.processing_tasks "
                "WHERE source_id=:sid ORDER BY created_at, id"
            ),
            {"sid": source_id},
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]


def test_worker_advances_source_to_queryable() -> None:
    submitted = _submit("wiki-hardware-spec")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "QUERYABLE"
    )
    assert (
        _scalar(
            "SELECT status FROM knowledge.document_versions WHERE id=:vid",
            vid=submitted["version_id"],
        )
        == "READY"
    )
    assert (
        str(
            _scalar(
                "SELECT current_version_id FROM knowledge.knowledge_sources WHERE id=:sid",
                sid=submitted["source_id"],
            )
        )
        == submitted["version_id"]
    )
    assert (
        _scalar(
            "SELECT processing_stage FROM knowledge.document_versions WHERE id=:vid",
            vid=submitted["version_id"],
        )
        is None
    )

    chain = _task_chain(submitted["source_id"])
    assert [c[0] for c in chain] == [
        "FETCH", "PARSE", "CLASSIFY", "CHUNK", "EMBED", "INDEX", "FINALIZE",
    ]
    assert all(c[1] == "SUCCEEDED" for c in chain)
    attempts = _scalar("SELECT count(*) FROM tasking.task_attempts")
    assert attempts >= 7


def test_worker_recovers_from_transient_retry() -> None:
    submitted = _submit("mock-fail-once-doc")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "QUERYABLE"
    )
    fetch = _task_chain(submitted["source_id"])[0]
    assert fetch[0] == "FETCH"
    assert fetch[1] == "SUCCEEDED"
    assert fetch[2] == 2  # 首次失败 + 重试成功

    with SessionLocal() as session:
        results = session.execute(
            text(
                "SELECT result FROM tasking.task_attempts ta "
                "JOIN tasking.processing_tasks t ON t.id=ta.task_id "
                "WHERE t.source_id=:sid AND t.task_type='FETCH' ORDER BY ta.attempt_no"
            ),
            {"sid": submitted["source_id"]},
        ).scalars().all()
    assert results == ["FAILED", "SUCCEEDED"]


def test_worker_marks_failed_on_permanent_error() -> None:
    submitted = _submit("mock-permanent-doc")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "FAILED"
    )
    assert (
        _scalar("SELECT status FROM knowledge.document_versions WHERE id=:vid", vid=submitted["version_id"])
        == "FAILED"
    )
    assert _scalar(
        "SELECT last_error_code FROM tasking.processing_tasks WHERE source_id=:sid", sid=submitted["source_id"]
    ) == "MOCK_PERMANENT"
    # 只创建了 FETCH 任务，未生成下游阶段
    assert len(_task_chain(submitted["source_id"])) == 1


def test_worker_transient_exhausts_to_failed() -> None:
    submitted = _submit("mock-transient-doc")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "FAILED"
    )
    fetch = _task_chain(submitted["source_id"])[0]
    assert fetch[1] == "FAILED"
    assert fetch[2] == 3  # max_attempts=3


def test_worker_classification_uncertain() -> None:
    submitted = _submit("mock-uncertain-doc")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "PENDING_CONFIRMATION"
    )
    assert (
        _scalar("SELECT status FROM knowledge.document_versions WHERE id=:vid", vid=submitted["version_id"])
        == "PENDING_CONFIRMATION"
    )
    # 流水线停在 CLASSIFY，不进入 CHUNK
    chain = _task_chain(submitted["source_id"])
    assert [c[0] for c in chain] == ["FETCH", "PARSE", "CLASSIFY"]
    assert chain[-1][1] == "SUCCEEDED"


def test_worker_classification_irrelevant() -> None:
    submitted = _submit("mock-irrelevant-doc")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "OFFLINE"
    )
    assert (
        _scalar("SELECT offline_reason FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "明确无关"
    )
    assert (
        _scalar("SELECT status FROM knowledge.document_versions WHERE id=:vid", vid=submitted["version_id"])
        == "FAILED"
    )


def test_worker_lease_reclaim_after_expiry() -> None:
    submitted = _submit("wiki-hardware-spec")
    source_id = submitted["source_id"]

    # 模拟一个已领取但崩溃的 Worker：任务 RUNNING、租约过期、存在未完成 attempt
    with SessionLocal() as session:
        session.execute(
            text(
                "UPDATE tasking.processing_tasks SET status='RUNNING', lease_owner='dead-worker', "
                "lease_expires_at=:exp, attempt_count=1 WHERE source_id=:sid"
            ),
            {
                "exp": datetime.now(timezone.utc) - timedelta(seconds=10),
                "sid": source_id,
            },
        )
        task_id = session.execute(
            text("SELECT id FROM tasking.processing_tasks WHERE source_id=:sid"), {"sid": source_id}
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO tasking.task_attempts (id, task_id, attempt_no, worker_id, started_at, result) "
                "VALUES (gen_random_uuid(), :tid, 1, 'dead-worker', now(), NULL)"
            ),
            {"tid": task_id},
        )
        session.commit()

    outcomes = _runner().claim_and_execute(batch_size=10)
    assert "SUCCEEDED" in outcomes
    # 旧 attempt 被标记 ABANDONED；来源可继续推进
    assert _scalar("SELECT count(*) FROM tasking.task_attempts WHERE result='ABANDONED'") == 1


def test_retry_after_failure_then_worker_succeeds() -> None:
    """手动重试后由 Worker 推进到 QUERYABLE（token 无失败标记，重试流水线成功）。"""
    submitted = _submit("wiki-hardware-spec")
    source_id = submitted["source_id"]

    # 模拟首版处理失败
    with SessionLocal() as session:
        session.execute(
            text(
                "UPDATE tasking.processing_tasks SET status='FAILED', last_error_code='SIMULATED' "
                "WHERE source_id=:sid"
            ),
            {"sid": source_id},
        )
        session.execute(
            text("UPDATE knowledge.document_versions SET status='FAILED' WHERE source_id=:sid"),
            {"sid": source_id},
        )
        session.execute(
            text("UPDATE knowledge.knowledge_sources SET status='FAILED' WHERE id=:sid"),
            {"sid": source_id},
        )
        session.commit()
    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=source_id)
        == "FAILED"
    )

    retry = client.post(f"/api/v1/knowledge-sources/{source_id}/retry")
    assert retry.status_code == 202

    _drain(_runner())
    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=source_id)
        == "QUERYABLE"
    )


def test_heartbeat_renews_lease() -> None:
    submitted = _submit("wiki-hardware-spec")
    task_id = submitted["task_id"]

    # 模拟任务被领取且执行中：RUNNING + 租约属于当前 worker
    with SessionLocal() as session:
        session.execute(
            text(
                "UPDATE tasking.processing_tasks SET status='RUNNING', lease_owner='test-worker', "
                "lease_expires_at=:exp WHERE id=:tid"
            ),
            {
                "exp": datetime.now(timezone.utc) + timedelta(seconds=30),
                "tid": task_id,
            },
        )
        session.commit()

    runner = _runner()
    assert runner.heartbeat(task_id, worker_id="test-worker") is True
    # 非租约持有者不能续租
    assert runner.heartbeat(task_id, worker_id="other-worker") is False
    assert _scalar(
        "SELECT lease_owner FROM tasking.processing_tasks WHERE id=:tid", tid=task_id
    ) == "test-worker"
