"""处理任务管理 API 测试（DD-03，仅管理员，只读）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.models.task import ProcessingTask
from app.db.session import SessionLocal
from app.main import app

from _seed_retrieval import make_user, user_cookies

client = TestClient(app)


def _cookies(*, is_admin: bool) -> dict:
    with SessionLocal() as s:
        user = make_user(s, is_admin=is_admin, display_name="任务测试用户")
        cookies = user_cookies(s, user)
        s.commit()
    return cookies


def test_admin_list_tasks_requires_admin() -> None:
    resp = client.get("/api/v1/admin/tasks", cookies=_cookies(is_admin=False))
    assert resp.status_code == 403


def test_admin_list_tasks_returns_seeded_task() -> None:
    with SessionLocal() as s:
        s.add(
            ProcessingTask(
                task_type="FETCH",
                status="PENDING",
                idempotency_key="admin-tasks:test:1",
                priority=100,
                max_attempts=3,
            )
        )
        s.commit()

    resp = client.get("/api/v1/admin/tasks", cookies=_cookies(is_admin=True))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] >= 1
    assert any(t["task_type"] == "FETCH" for t in data["items"])


def test_admin_list_tasks_filters_by_type() -> None:
    with SessionLocal() as s:
        s.add_all(
            [
                ProcessingTask(task_type="FETCH", status="PENDING", idempotency_key="admin-tasks:f", priority=100, max_attempts=3),
                ProcessingTask(task_type="INDEX", status="PENDING", idempotency_key="admin-tasks:i", priority=100, max_attempts=3),
            ]
        )
        s.commit()

    resp = client.get("/api/v1/admin/tasks", params={"task_type": "INDEX"}, cookies=_cookies(is_admin=True))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert all(t["task_type"] == "INDEX" for t in data["items"])
    assert len(data["items"]) == 1
