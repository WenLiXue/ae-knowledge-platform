"""运行日志系统测试。

覆盖：JSON formatter 结构化输出、访问日志 + X-Request-ID（含 query 脱敏）、
ERROR 级日志落库 platform.log_events、Worker 阶段日志字段、Worker 终态失败落库、
飞书外部调用日志、管理端系统日志查询的鉴权与筛选。
"""

from __future__ import annotations

import json
import logging
import tempfile

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import sessions
from app.core.config import get_settings
from app.core.context import (
    ContextFilter,
    RequestContext,
    reset_request_context,
    set_request_context,
    set_service,
)
from app.core.logging import JsonFormatter
from app.db.models.user import User
from app.db.session import SessionLocal
from app.feishu_provider.real import RealFeishuProvider
from app.main import app
from app.storage.local import LocalObjectStore
from app.worker.runner import WorkerRunner


client = TestClient(app)


class _CapturingHandler(logging.Handler):
    """带 ContextFilter 的收集 handler（用于断言任务上下文注入）。"""

    def __init__(self) -> None:
        super().__init__()
        self.addFilter(ContextFilter())
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _make_user(is_admin: bool) -> dict:
    with SessionLocal() as s:
        user = User(
            display_name="管理员" if is_admin else "普通用户",
            status="ACTIVE",
            is_admin=is_admin,
            created_source="ADMIN",
        )
        s.add(user)
        s.commit()
        s.refresh(user)
        token = sessions.create_session(s, user.id, 24)
        s.commit()
        return {get_settings().session_cookie_name: token}


@pytest.fixture()
def admin() -> dict:
    return _make_user(True)


@pytest.fixture()
def user() -> dict:
    return _make_user(False)


@pytest.fixture()
def worker_service() -> None:
    """模拟 Worker 进程：service 标记为 worker，用后恢复 api。"""
    set_service("worker")
    yield
    set_service("api")


def _submit(token: str) -> dict:
    response = client.post(
        "/api/v1/feishu/documents/submit",
        json={
            "items": [
                {"client_item_id": "log-test", "resource_token": token, "resource_type": "wiki"}
            ]
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]["items"][0]


def _runner() -> WorkerRunner:
    return WorkerRunner(
        worker_id="test-worker",
        retry_base_delay_seconds=0.0,
        lease_seconds=60,
        store=LocalObjectStore(tempfile.mkdtemp(prefix="ae-test-storage-")),
    )


def _drain(runner: WorkerRunner, max_cycles: int = 40) -> None:
    for _ in range(max_cycles):
        runner.claim_and_execute(batch_size=10)
        with SessionLocal() as session:
            open_tasks = session.execute(
                text(
                    "SELECT count(*) FROM tasking.processing_tasks "
                    "WHERE status IN ('PENDING', 'RUNNING', 'RETRY_WAIT')"
                )
            ).scalar_one()
        if open_tasks == 0:
            return
    raise AssertionError("Worker 未在预期轮次内排空任务")


def _count_log_events(**where: str) -> int:
    conds = " AND ".join(f"{key} = :p_{key}" for key in where)
    params = {f"p_{key}": value for key, value in where.items()}
    sql = "SELECT count(*) FROM platform.log_events"
    if conds:
        sql += f" WHERE {conds}"
    with SessionLocal() as session:
        return session.execute(text(sql), params).scalar_one()


# ---- JSON formatter ----

def test_json_formatter_emits_structured_line() -> None:
    token = set_request_context(RequestContext(request_id="req-123", ip="127.0.0.1"))
    try:
        record = logging.LogRecord(
            name="app.test", level=logging.INFO, pathname=__file__, lineno=1,
            msg="hello %s", args=("world",), exc_info=None,
        )
        ContextFilter().filter(record)
        data = json.loads(JsonFormatter().format(record))
    finally:
        reset_request_context(token)
    assert data["level"] == "INFO"
    assert data["message"] == "hello world"
    assert data["request_id"] == "req-123"
    assert data["ip"] == "127.0.0.1"
    assert data["service"] == "api"


# ---- 访问日志 + X-Request-ID ----

def test_access_log_records_request_and_header(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.api.access"):
        resp = client.get("/health")
    assert resp.status_code == 200
    request_id = resp.headers.get("X-Request-ID")
    assert request_id

    access = [r for r in caplog.records if r.getMessage() == "http_request"]
    assert access
    rec = access[0]
    assert rec.status == 200
    assert rec.method == "GET"
    assert rec.path == "/health"
    assert rec.request_id == request_id


def test_access_log_sanitizes_sensitive_query(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.api.access"):
        client.get("/health?search_key=my-question&ok=1")
    access = [r for r in caplog.records if r.getMessage() == "http_request"]
    assert access
    query = access[0].query
    assert "my-question" not in query
    assert "search_key=***" in query
    assert "ok=1" in query


# ---- ERROR 落库 ----

def test_db_handler_persists_error_on_logger_error() -> None:
    before = _count_log_events()
    token = set_request_context(
        RequestContext(request_id="req-persist", user_id="11111111-1111-1111-1111-111111111111")
    )
    try:
        logging.getLogger("app.test").error("boom", extra={"error_code": "E_TEST"})
    finally:
        reset_request_context(token)

    assert _count_log_events() == before + 1
    with SessionLocal() as session:
        row = session.execute(
            text(
                "SELECT message, request_id, error_code, service, user_id "
                "FROM platform.log_events ORDER BY created_at DESC, id DESC LIMIT 1"
            )
        ).one()
    assert row[0] == "boom"
    assert row[1] == "req-persist"
    assert row[2] == "E_TEST"
    assert row[3] == "api"
    assert str(row[4]) == "11111111-1111-1111-1111-111111111111"


# ---- Worker 阶段日志 ----

def test_worker_stage_log_fields(worker_service: None) -> None:
    _submit("wiki-hardware-spec")
    handler = _CapturingHandler()
    pipeline_logger = logging.getLogger("app.worker.pipeline")
    pipeline_logger.addHandler(handler)
    try:
        _drain(_runner())
    finally:
        pipeline_logger.removeHandler(handler)

    stage_records = [r for r in handler.records if r.getMessage() == "stage_start"]
    assert stage_records
    rec = stage_records[0]
    assert rec.task_id
    assert rec.source_id
    assert rec.version_id
    assert rec.task_type == "FETCH"
    assert rec.service == "worker"


def test_worker_failure_persists_error(worker_service: None) -> None:
    submitted = _submit("mock-permanent-doc")
    _drain(_runner())

    assert _count_log_events(service="worker", level="ERROR") >= 1
    with SessionLocal() as session:
        row = session.execute(
            text(
                "SELECT message, task_id, source_id, version_id "
                "FROM platform.log_events WHERE service='worker' ORDER BY created_at DESC, id DESC LIMIT 1"
            )
        ).one()
    assert row[0] == "task_failed"
    assert row[1] == submitted["task_id"]
    assert row[2] == submitted["source_id"]
    assert row[3] == submitted["version_id"]


# ---- 飞书外部调用日志 ----

def test_feishu_provider_logs_external_call(caplog) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "data": {"files": [], "next_page_token": None}})

    provider = RealFeishuProvider(
        app_id="app", app_secret="secret", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with caplog.at_level(logging.INFO, logger="app.integration.feishu"):
        result = provider.list_documents(user_access_token="tok", resource_types=["file"], limit=20)

    assert result.items == []
    calls = [r for r in caplog.records if r.getMessage() == "external_call"]
    assert calls
    rec = calls[0]
    assert rec.result == "ok"
    assert rec.status == 200
    assert rec.path == "/open-apis/drive/v1/files"
    assert rec.dependency == "feishu"


# ---- 管理端系统日志查询 ----

def test_admin_system_logs_auth_and_filters(admin: dict, user: dict) -> None:
    from app.db.models.log import LogEvent

    with SessionLocal() as session:
        session.add_all(
            [
                LogEvent(service="api", level="ERROR", message="boom one", error_code="E1", request_id="r1"),
                LogEvent(service="api", level="ERROR", message="boom two", error_code="E2"),
                LogEvent(service="worker", level="WARNING", message="task retry"),
            ]
        )
        session.commit()

    assert client.get("/api/v1/admin/system-logs").status_code == 401
    assert client.get("/api/v1/admin/system-logs", cookies=user).status_code == 403

    resp = client.get("/api/v1/admin/system-logs", cookies=admin)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 3

    resp = client.get("/api/v1/admin/system-logs?level=ERROR&service=api", cookies=admin)
    assert resp.json()["data"]["total"] == 2

    resp = client.get("/api/v1/admin/system-logs?keyword=boom", cookies=admin)
    assert resp.json()["data"]["total"] == 2

    resp = client.get("/api/v1/admin/system-logs?request_id=r1", cookies=admin)
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["error_code"] == "E1"
