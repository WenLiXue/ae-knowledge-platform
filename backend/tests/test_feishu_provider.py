"""飞书文档接入测试：Fake/Real Provider 与 Worker FETCH 阶段。

覆盖：Fake 发现/解析/正文、发现接口走 provider、Worker FETCH 授权失效(AUTH)、
文档不存在(NOT_FOUND)、限流重试、文档更新触发新版本续处理、Worker 重启续处理、
Real provider 错误映射（httpx.MockTransport，不联调真实飞书）。
"""

from __future__ import annotations

import tempfile

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import SessionLocal
from app.feishu_provider.base import AUTH, NOT_FOUND, PERMISSION, RATE_LIMIT, TIMEOUT, FeishuError
from app.feishu_provider.fake import FakeFeishuProvider
from app.feishu_provider.feishu_document_provider import RealFeishuProvider
from app.main import app
from app.storage.local import LocalObjectStore
from app.worker.runner import WorkerRunner


client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticate_api_client() -> None:
    """文档 API 要求有效平台会话；Provider 单元测试也可共享该登录态。"""
    client.cookies.clear()
    start = client.post("/api/v1/auth/feishu/start").json()["data"]
    response = client.get(
        f"/api/v1/auth/feishu/callback?code=auth-code&state={start['state']}",
        follow_redirects=False,
    )
    assert response.status_code == 302
    yield
    client.cookies.clear()


def _submit(token: str, resource_type: str = "wiki", client_item_id: str = "row-1") -> dict:
    response = client.post(
        "/api/v1/feishu/documents/submit",
        json={
            "items": [
                {
                    "client_item_id": client_item_id,
                    "resource_token": token,
                    "resource_type": resource_type,
                }
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
    # 排空到无未终结任务：即使某轮 claim 偶发返回空也继续，保证确定性
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


def _scalar(sql: str, **params):
    with SessionLocal() as session:
        return session.execute(text(sql), params).scalar_one()


# ---- Fake provider 基础行为 ----


def test_fake_provider_discovery_and_metadata() -> None:
    provider = FakeFeishuProvider()
    result = provider.list_documents(user_access_token=None, query="白皮书")
    assert len(result.items) == 1
    assert result.items[0].resource_token == "docx-product-whitepaper"

    meta = provider.get_metadata(None, "wiki-hardware-spec", "wiki")
    assert meta.title == "AE 产品硬件规格"
    assert meta.revision == "mock-rev-1"

    resolved = provider.resolve_url(None, "https://xx.feishu.cn/wiki/wikixyz123")
    assert resolved.resource_token == "wikixyz123"
    assert resolved.resource_type == "wiki"

    file_resolved = provider.resolve_url(None, "https://xx.feishu.cn/file/filexyz123#page_number=0")
    assert file_resolved.resource_token == "filexyz123"
    assert file_resolved.resource_type == "file"

    content = provider.fetch_content(None, "wiki-hardware-spec", "wiki")
    assert "T90000" in content.text
    assert content.revision == "mock-rev-1"


def test_fake_provider_raises_on_bad_url() -> None:
    provider = FakeFeishuProvider()
    with pytest.raises(FeishuError) as excinfo:
        provider.resolve_url(None, "https://example.com/unknown")
    assert excinfo.value.category in ("VALIDATION",)


# ---- 发现接口走 provider 且标记已提交 ----


def test_discovery_api_uses_provider() -> None:
    listing = client.get("/api/v1/feishu/documents")
    assert listing.status_code == 200
    items = listing.json()["data"]["items"]
    assert {i["resource_token"] for i in items} >= {
        "wiki-hardware-spec", "docx-product-whitepaper", "wiki-seg-cases",
    }
    # 提交后再次发现应标记已提交
    submitted = _submit("wiki-hardware-spec")
    after = client.get("/api/v1/feishu/documents").json()["data"]["items"]
    hw = next(i for i in after if i["resource_token"] == "wiki-hardware-spec")
    assert hw["submitted"] is True
    assert hw["source_id"] == submitted["source_id"]


def test_submit_document_link_resolves_and_queues_source() -> None:
    response = client.post(
        "/api/v1/feishu/documents/submit-links",
        json={"urls": ["https://example.feishu.cn/wiki/wiki-hardware-spec"]},
    )
    assert response.status_code == 202, response.text
    item = response.json()["data"]["items"][0]
    assert item["resource_token"] == "wiki-hardware-spec"
    assert item["status"] == "PROCESSING"


# ---- Worker FETCH：授权失效 / 不存在 / 限流重试 ----


def test_worker_fetch_auth_failure_marks_auth_category() -> None:
    submitted = _submit("mock-auth-fail-doc")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "FAILED"
    )
    assert (
        _scalar("SELECT last_error_category FROM tasking.processing_tasks WHERE source_id=:sid", sid=submitted["source_id"])
        == "AUTH"
    )
    assert (
        _scalar("SELECT last_error_code FROM tasking.processing_tasks WHERE source_id=:sid", sid=submitted["source_id"])
        == "FEISHU_AUTH_EXPIRED"
    )


def test_worker_fetch_not_found() -> None:
    submitted = _submit("mock-missing-doc")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "FAILED"
    )
    assert (
        _scalar("SELECT last_error_category FROM tasking.processing_tasks WHERE source_id=:sid", sid=submitted["source_id"])
        == "NOT_FOUND"
    )
    # 未生成下游任务
    with SessionLocal() as session:
        count = session.execute(
            text("SELECT count(*) FROM tasking.processing_tasks WHERE source_id=:sid"),
            {"sid": submitted["source_id"]},
        ).scalar_one()
    assert count == 1


def test_worker_fetch_ratelimit_retries_then_succeeds() -> None:
    submitted = _submit("mock-ratelimit-once-doc")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "QUERYABLE"
    )
    fetch_attempts = _scalar(
        "SELECT attempt_count FROM tasking.processing_tasks WHERE source_id=:sid AND task_type='FETCH'",
        sid=submitted["source_id"],
    )
    assert fetch_attempts == 2  # 首次限流失败 + 重试成功


# ---- Worker FETCH：文档更新 → 新版本续处理 ----


def test_worker_fetch_doc_updated_bumps_version() -> None:
    submitted = _submit("wiki-hardware-spec")
    source_id = submitted["source_id"]
    version_id = submitted["version_id"]

    # 模拟已记录版本与当前获取不一致（文档被编辑）
    with SessionLocal() as session:
        session.execute(
            text("UPDATE knowledge.document_versions SET external_revision='rev-stale' WHERE id=:vid"),
            {"vid": version_id},
        )
        session.commit()

    runner = _runner()
    runner.claim_and_execute(batch_size=10)

    with SessionLocal() as session:
        versions = session.execute(
            text(
                "SELECT version_no, status, error_code FROM knowledge.document_versions "
                "WHERE source_id=:sid ORDER BY version_no"
            ),
            {"sid": source_id},
        ).fetchall()
    assert versions == [
        (1, "FAILED", "DOC_REVISION_CHANGED"),
        (2, "PROCESSING", None),
    ]

    # 新版本从 FETCH 重跑，最终激活
    _drain(runner)
    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=source_id)
        == "QUERYABLE"
    )
    assert (
        _scalar("SELECT version_no FROM knowledge.document_versions WHERE status='READY' AND source_id=:sid", sid=source_id)
        == 2
    )


# ---- Worker 重启后继续处理 ----


def test_worker_restart_continues_pipeline() -> None:
    submitted = _submit("wiki-hardware-spec")
    source_id = submitted["source_id"]
    # 对象存储在进程重启后保持持久（raw/parsed 对象可读），两个 runner 共享同一 store
    store = LocalObjectStore(tempfile.mkdtemp(prefix="ae-test-storage-"))

    # 第一段：只处理 FETCH，PARSE 排队
    runner1 = WorkerRunner(
        worker_id="test-worker", retry_base_delay_seconds=0.0, lease_seconds=60, store=store
    )
    runner1.claim_and_execute(batch_size=10)
    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=source_id)
        == "PROCESSING"
    )

    # 模拟进程重启：新 runner（新 provider，对象存储仍持久）继续处理剩余阶段
    runner2 = WorkerRunner(
        worker_id="test-worker", retry_base_delay_seconds=0.0, lease_seconds=60, store=store
    )
    _drain(runner2)
    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=source_id)
        == "QUERYABLE"
    )


# ---- Real provider 错误映射（httpx.MockTransport，不联调真实飞书） ----


def _real_provider(handler) -> RealFeishuProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return RealFeishuProvider(app_id="app", app_secret="secret", http_client=client)


def test_real_provider_requires_user_token() -> None:
    provider = _real_provider(lambda req: httpx.Response(200, json={"code": 0, "data": {}}))
    with pytest.raises(FeishuError) as excinfo:
        provider.fetch_content(None, "doc-x", "docx")
    assert excinfo.value.category == AUTH
    assert excinfo.value.code == "USER_TOKEN_MISSING"


def test_real_provider_maps_feishu_error_codes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t", "expire": 7200})
        token = path.rsplit("/", 1)[-1]
        codes = {
            "ratelimit-doc": 910002,
            "authexp-doc": 99991664,
            "missing-doc": 1061002,
        }
        if token in codes:
            return httpx.Response(200, json={"code": codes[token], "msg": "err", "data": {}})
        return httpx.Response(200, json={"code": 0, "data": {"document": {"title": "T", "revision": "1", "create_time": "0"}}})

    provider = _real_provider(handler)

    with pytest.raises(FeishuError) as excinfo:
        provider.get_metadata("u-token", "ratelimit-doc", "docx")
    assert excinfo.value.category == RATE_LIMIT
    assert excinfo.value.retryable is True

    with pytest.raises(FeishuError) as excinfo:
        provider.get_metadata("u-token", "authexp-doc", "docx")
    assert excinfo.value.category == AUTH
    assert excinfo.value.retryable is False

    with pytest.raises(FeishuError) as excinfo:
        provider.get_metadata("u-token", "missing-doc", "docx")
    assert excinfo.value.category == NOT_FOUND

    # 正常文档成功解析
    doc = provider.get_metadata("u-token", "ok-doc", "docx")
    assert doc.title == "T"


def test_real_provider_maps_http_status_and_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t", "expire": 7200})
        token = path.rsplit("/", 1)[-1]
        if token == "ratelimit-http":
            return httpx.Response(429, text="rate limited")
        raise httpx.ReadTimeout("simulated timeout")

    provider = _real_provider(handler)

    with pytest.raises(FeishuError) as excinfo:
        provider.get_metadata("u-token", "ratelimit-http", "docx")
    assert excinfo.value.category == RATE_LIMIT

    with pytest.raises(FeishuError) as excinfo:
        provider.get_metadata("u-token", "timeout-doc", "docx")
    assert excinfo.value.category == TIMEOUT
    assert excinfo.value.retryable is True


def test_real_provider_resolves_wiki_sheet_and_reads_selected_tab() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/wiki/v2/spaces/get_node"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"node": {"obj_token": "spreadsheet-x", "obj_type": "sheet", "title": "需求表"}},
                },
            )
        if path.endswith("/sheets/v3/spreadsheets/spreadsheet-x"):
            return httpx.Response(
                200,
                json={"code": 0, "data": {"spreadsheet": {"token": "spreadsheet-x", "title": "需求表"}}},
            )
        if path.endswith("/sheets/v3/spreadsheets/spreadsheet-x/sheets/query"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"sheets": [
                        {"sheet_id": "tab-a", "title": "需求", "hidden": False,
                         "grid_properties": {"row_count": 2, "column_count": 2}},
                        {"sheet_id": "tab-b", "title": "隐藏", "hidden": True,
                         "grid_properties": {"row_count": 10, "column_count": 5}},
                    ]},
                },
            )
        if "/values/" in path:
            return httpx.Response(
                200,
                json={"code": 0, "data": {"revision": 9, "valueRange": {
                    "range": "tab-a!A1:B2", "revision": 9,
                    "values": [["编号", "名称"], ["F01", "接口联动"]],
                }}},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    provider = _real_provider(handler)
    url = "https://example.feishu.cn/wiki/wiki-node?sheet=tab-a"
    meta = provider.resolve_url("u-token", url)
    assert meta.resource_token == "spreadsheet-x"
    assert meta.resource_type == "sheet"
    assert meta.canonical_token == "spreadsheet-x#tab-a"

    content = provider.fetch_content("u-token", meta.resource_token, "sheet", source_url=url)
    assert content.content_type == "sheet"
    assert content.revision == "9"
    assert content.raw_payload["sheets"][0]["sheet_id"] == "tab-a"
    assert content.raw_payload["sheets"][0]["values"][1] == ["F01", "接口联动"]
    assert not any("tab-b" in str(request.url) for request in requests if "/values/" in request.url.path)


def test_real_provider_rejects_unknown_selected_sheet() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sheets/v3/spreadsheets/spreadsheet-x/sheets/query"):
            return httpx.Response(200, json={"code": 0, "data": {"sheets": []}})
        if request.url.path.endswith("/sheets/v3/spreadsheets/spreadsheet-x"):
            return httpx.Response(200, json={"code": 0, "data": {"spreadsheet": {"title": "T"}}})
        raise AssertionError(f"unexpected request: {request.url}")

    provider = _real_provider(handler)
    with pytest.raises(FeishuError) as excinfo:
        provider.fetch_content(
            "u-token", "spreadsheet-x", "sheet",
            source_url="https://example.feishu.cn/sheets/spreadsheet-x?sheet=missing",
        )
    assert excinfo.value.category == NOT_FOUND
    assert excinfo.value.code == "SHEET_NOT_FOUND"


def test_real_provider_maps_http_403_to_resource_permission() -> None:
    provider = _real_provider(lambda req: httpx.Response(403, json={"code": 1310213, "msg": "Permission Fail"}))
    with pytest.raises(FeishuError) as excinfo:
        provider.get_metadata("u-token", "sheet-x", "sheet")
    assert excinfo.value.category == PERMISSION
