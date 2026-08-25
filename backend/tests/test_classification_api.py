"""真实分类流水线与人工确认 API 的集成测试（DD-19 §18.2、§9）。

覆盖：
- feature_real_classification 开启下 CLASSIFY 走真实分类：RELEVANT 进 CHUNK、
  UNCERTAIN 进待确认、IRRELEVANT 来源下线、非法 JSON 一次修复、模型未配置禁止默认相关；
- 相同 input_hash 复用已验证结果（幂等）；
- 人工确认 API：列表/详情、确认相关（CHUNK 任务 + MANUAL 字段来源）、
  确认无关、重分类形成新 input_hash、row_version 冲突、非管理员 403、审计落库；
- 分类配置加载：默认配置 revision=0、自定义 ACTIVE revision 生效。

模型调用用 FakeClassificationGateway 注入（monkeypatch pipeline.create_gateway）。
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.model_gateway.base import ChatResponse, ChatUsage
from app.storage.local import LocalObjectStore
from app.worker.runner import WorkerRunner

client = TestClient(app)

_SYSTEM_USER_ID = "11111111-1111-1111-1111-111111111111"

BASELINE_DOCUMENT_TYPES = [
    ("product-spec", "产品规格", 10),
    ("product-whitepaper", "产品白皮书", 20),
    ("requirement", "需求说明书", 30),
    ("design", "设计文档", 40),
    ("deployment-guide", "部署说明", 50),
    ("operation-manual", "操作手册", 60),
    ("test-report", "测试报告", 70),
    ("fault-analysis", "故障分析", 80),
    ("seg-case", "SEG 问题案件", 90),
    ("compatibility-list", "兼容性清单", 100),
    ("release-note", "版本说明", 110),
    ("other", "其他资料", 999),
]


# ---- 基础设施 ----

def _make_user(is_admin: bool) -> dict:
    from app.auth import sessions
    from app.db.models.user import User

    with SessionLocal() as s:
        user = User(display_name="测试管理员" if is_admin else "普通用户", status="ACTIVE", is_admin=is_admin, created_source="ADMIN")
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


def _seed_catalog() -> None:
    from app.db.models.catalog import DocumentType, Product, ProductVersion

    with SessionLocal() as s:
        for code, name, sort_order in BASELINE_DOCUMENT_TYPES:
            s.add(DocumentType(code=code, name=name, sort_order=sort_order))
        product = Product(code="TDA", name="TDA")
        s.add(product)
        s.flush()
        s.add(ProductVersion(product_id=product.id, version_code="7.0.3", sort_order=0))
        s.commit()


def _seed_llm_classification_model() -> str:
    from app.llm import service as llm_service
    from app.llm.schemas import LlmModelCreate, ServiceBindingsUpdate

    with SessionLocal() as s:
        model = llm_service.create_model(
            s,
            LlmModelCreate(
                name="分类模型",
                model_type="CHAT",
                provider="openai-compatible",
                base_url="https://llm.test.local/v1",
                model_name="test-classifier",
                api_key="sk-test",
            ),
            user_id=_SYSTEM_USER_ID,
        )
        revision = llm_service.list_models(s)["revision"]
        llm_service.update_service_bindings(
            s,
            ServiceBindingsUpdate(
                expected_revision=revision,
                bindings={
                    "QA": model["id"],
                    "DOCUMENT_CLASSIFICATION": model["id"],
                    "DOCUMENT_EMBEDDING": None,
                    "RETRIEVAL_RERANK": None,
                },
            ),
            user_id=_SYSTEM_USER_ID,
        )
        s.commit()
        return model["id"]


def _seed_classification_config(content: dict) -> int:
    from app.db.models.config import ConfigRevision

    with SessionLocal() as s:
        rev = ConfigRevision(
            namespace="classification",
            content=content,
            status="ACTIVE",
            created_by_user_id=_SYSTEM_USER_ID,
            activated_at=datetime.now(timezone.utc),
        )
        s.add(rev)
        s.commit()
        return rev.id


@pytest.fixture()
def real_classification(monkeypatch):
    """开启真实分类开关并注入假网关。"""
    import app.worker.pipeline as pipeline_module

    monkeypatch.setattr(get_settings(), "feature_real_classification", True)
    monkeypatch.setattr(
        pipeline_module, "create_gateway", lambda resolved: FakeClassificationGateway()
    )
    yield


def _relevant_output() -> dict:
    return {
        "relevance": "RELEVANT",
        "relevance_confidence": 0.95,
        "product_code": "TDA",
        "product_version_code": "7.0.3",
        "document_type_code": "deployment-guide",
        "product_form_code": None,
        "is_domestic": None,
        "module_name": None,
        "business_topic": "硬件部署",
        "keywords": ["部署", "TDA"],
        "summary": "TDA 7.0.3 部署文档",
        "field_confidence": {"document_type": 0.9},
        "evidence": [{"field": "relevance", "locator_ids": ["title"], "excerpts": ["TDA"]}],
        "missing_fields": [],
        "reason_summary": "标题与正文涉及 TDA 部署",
    }


def _uncertain_output() -> dict:
    return {
        "relevance": "UNCERTAIN",
        "relevance_confidence": 0.5,
        "product_code": None,
        "product_version_code": None,
        "document_type_code": None,
        "product_form_code": None,
        "is_domestic": None,
        "module_name": None,
        "business_topic": None,
        "keywords": [],
        "summary": None,
        "field_confidence": {},
        "evidence": [],
        "missing_fields": ["document_type"],
        "reason_summary": "证据不足，无法判断相关性",
    }


def _irrelevant_output() -> dict:
    return {
        "relevance": "IRRELEVANT",
        "relevance_confidence": 0.96,
        "product_code": None,
        "product_version_code": None,
        "document_type_code": None,
        "product_form_code": None,
        "is_domestic": None,
        "module_name": None,
        "business_topic": None,
        "keywords": [],
        "summary": None,
        "field_confidence": {},
        "evidence": [{"field": "relevance", "locator_ids": ["title"], "excerpts": []}],
        "missing_fields": [],
        "reason_summary": "与平台产品知识无关",
    }


class FakeClassificationGateway:
    """按用户消息中标题标记路由的确定性假网关。"""

    def __init__(self):
        self.calls: list = []

    def chat(self, request):
        self.calls.append(request)
        user_content = next(
            (m["content"] for m in request.messages if m["role"] == "user"), ""
        )
        index = len(self.calls) - 1
        if "cls-invalid-once" in user_content:
            if index == 0:
                return self._resp(request, "不是合法 JSON {{{")
            return self._resp(request, json.dumps(_relevant_output()))
        if "cls-uncertain" in user_content:
            return self._resp(request, json.dumps(_uncertain_output()))
        if "cls-irrelevant" in user_content:
            return self._resp(request, json.dumps(_irrelevant_output()))
        return self._resp(request, json.dumps(_relevant_output()))

    def _resp(self, request, content: str) -> ChatResponse:
        return ChatResponse(
            model=request.model,
            content=content,
            usage=ChatUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


# ---- Worker 辅助（与 test_worker 同构） ----

def _submit(token: str) -> dict:
    response = client.post(
        "/api/v1/feishu/documents/submit",
        json={"items": [{"client_item_id": "row-1", "resource_token": token, "resource_type": "wiki"}]},
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]["items"][0]


def _runner() -> WorkerRunner:
    return WorkerRunner(
        worker_id="test-worker",
        retry_base_delay_seconds=0.0,
        lease_seconds=60,
        store=LocalObjectStore(tempfile.mkdtemp(prefix="ae-cls-test-storage-")),
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


def _scalar(sql: str, **params):
    with SessionLocal() as session:
        return session.execute(text(sql), params).scalar_one()


# ---- 真实分类：流水线 ----

def test_real_classification_relevant_reaches_queryable(real_classification, admin) -> None:
    _seed_catalog()
    _seed_llm_classification_model()
    submitted = _submit("cls-relevant-doc")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "QUERYABLE"
    )
    result = _scalar(
        "SELECT relevance FROM knowledge.classification_results WHERE version_id=:vid",
        vid=submitted["version_id"],
    )
    assert result == "RELEVANT"
    assert (
        _scalar("SELECT count(*) FROM knowledge.document_metadata WHERE version_id=:vid", vid=submitted["version_id"])
        == 1
    )


def test_real_classification_uncertain_goes_pending(real_classification, admin) -> None:
    _seed_catalog()
    _seed_llm_classification_model()
    submitted = _submit("cls-uncertain-doc")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "PENDING_CONFIRMATION"
    )
    assert (
        _scalar("SELECT status FROM knowledge.document_versions WHERE id=:vid", vid=submitted["version_id"])
        == "PENDING_CONFIRMATION"
    )
    # UNCERTAIN 不创建 metadata、不进入 CHUNK
    assert (
        _scalar("SELECT count(*) FROM knowledge.document_metadata WHERE version_id=:vid", vid=submitted["version_id"])
        == 0
    )
    chain = _scalar(
        "SELECT count(*) FROM tasking.processing_tasks WHERE version_id=:vid AND task_type='CHUNK'",
        vid=submitted["version_id"],
    )
    assert chain == 0


def test_real_classification_irrelevant_offlines_source(real_classification, admin) -> None:
    _seed_catalog()
    _seed_llm_classification_model()
    submitted = _submit("cls-irrelevant-doc")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "OFFLINE"
    )
    assert (
        _scalar("SELECT status FROM knowledge.document_versions WHERE id=:vid", vid=submitted["version_id"])
        == "FAILED"
    )
    assert (
        _scalar("SELECT error_code FROM knowledge.document_versions WHERE id=:vid", vid=submitted["version_id"])
        == "CLASSIFIED_IRRELEVANT"
    )


def test_real_classification_invalid_json_repairs_once(real_classification, admin) -> None:
    _seed_catalog()
    _seed_llm_classification_model()
    submitted = _submit("cls-invalid-once")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "QUERYABLE"
    )
    assert (
        _scalar("SELECT relevance FROM knowledge.classification_results WHERE version_id=:vid", vid=submitted["version_id"])
        == "RELEVANT"
    )


def test_real_classification_without_model_fails_not_default_relevant(real_classification, admin) -> None:
    _seed_catalog()
    # 不配置 DOCUMENT_CLASSIFICATION 模型：禁止默认相关，任务失败
    submitted = _submit("cls-relevant-doc")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "FAILED"
    )
    assert (
        _scalar("SELECT count(*) FROM knowledge.classification_results WHERE version_id=:vid", vid=submitted["version_id"])
        == 0
    )
    assert (
        _scalar(
            "SELECT last_error_code FROM tasking.processing_tasks WHERE version_id=:vid AND task_type='CLASSIFY'",
            vid=submitted["version_id"],
        )
        == "REQUIRED_SERVICE_MODEL_MISSING"
    )


def test_real_classification_unsupported_provider_fails_cleanly(monkeypatch, admin) -> None:
    """create_gateway 抛 CONFIG 类 GatewayError（不支持的服务商）→ 立即 FAILED 并带稳定错误码，
    不当作 INTERNAL 重试（DD-19 §16）。"""
    import app.worker.pipeline as pipeline_module
    from app.model_gateway.errors import GatewayError

    monkeypatch.setattr(get_settings(), "feature_real_classification", True)
    monkeypatch.setattr(
        pipeline_module,
        "create_gateway",
        lambda resolved: (_ for _ in ()).throw(
            GatewayError("CONFIG", "UNSUPPORTED_PROVIDER", "不支持的模型供应商: xxx", retryable=False)
        ),
    )
    _seed_catalog()
    _seed_llm_classification_model()
    submitted = _submit("cls-relevant-doc")
    _drain(_runner())

    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "FAILED"
    )
    assert (
        _scalar(
            "SELECT last_error_code FROM tasking.processing_tasks WHERE version_id=:vid AND task_type='CLASSIFY'",
            vid=submitted["version_id"],
        )
        == "UNSUPPORTED_PROVIDER"
    )
    assert (
        _scalar(
            "SELECT attempt_count FROM tasking.processing_tasks WHERE version_id=:vid AND task_type='CLASSIFY'",
            vid=submitted["version_id"],
        )
        == 1  # 非重试错误立即失败，不重试
    )


def test_real_classification_same_input_hash_reuses_result(real_classification, admin) -> None:
    """重跑相同 input_hash 只产生一个有效结果（AC-CLS-005、DD-05 §9）。"""
    _seed_catalog()
    _seed_llm_classification_model()
    submitted = _submit("cls-relevant-doc")
    _drain(_runner())

    with SessionLocal() as session:
        session.execute(
            text(
                "UPDATE tasking.processing_tasks SET status='FAILED', last_error_code='SIMULATED' "
                "WHERE version_id=:vid"
            ),
            {"vid": submitted["version_id"]},
        )
        session.execute(
            text("UPDATE knowledge.document_versions SET status='FAILED' WHERE id=:vid"),
            {"vid": submitted["version_id"]},
        )
        session.execute(
            text("UPDATE knowledge.knowledge_sources SET status='FAILED' WHERE id=:sid"),
            {"sid": submitted["source_id"]},
        )
        session.commit()

    # 手动重试：从 CLASSIFY 重跑，应复用已有 VALID 结果而不重复调用模型
    retry = client.post(f"/api/v1/knowledge-sources/{submitted['source_id']}/retry")
    assert retry.status_code == 202
    _drain(_runner())

    count = _scalar(
        "SELECT count(*) FROM knowledge.classification_results WHERE version_id=:vid",
        vid=submitted["version_id"],
    )
    assert count == 1
    assert (
        _scalar("SELECT status FROM knowledge.knowledge_sources WHERE id=:sid", sid=submitted["source_id"])
        == "QUERYABLE"
    )


# ---- 分类配置加载 ----

def test_classification_config_default_revision_zero() -> None:
    from app.classify.config import load_classification_config

    with SessionLocal() as session:
        config = load_classification_config(session)
    assert config.config_revision == 0
    assert config.thresholds["relevant"] == 0.80
    assert config.thresholds["irrelevant"] == 0.90


def test_classification_config_active_revision_overrides() -> None:
    from app.classify.config import load_classification_config

    rev_id = _seed_classification_config(
        {
            "schema_version": "1",
            "thresholds": {"relevant": 0.85, "irrelevant": 0.95},
            "prompt_revision": "2",
            "input_builder_revision": "1",
            "relevance_policy": {"definition": "自定义定义", "positive_examples": [], "negative_examples": []},
        }
    )
    with SessionLocal() as session:
        config = load_classification_config(session)
    assert config.config_revision == rev_id
    assert config.thresholds["relevant"] == 0.85
    assert config.prompt_revision == "2"


# ---- 人工确认 API ----

def _submit_pending() -> tuple[str, str]:
    _seed_catalog()
    _seed_llm_classification_model()
    submitted = _submit("cls-uncertain-doc")
    _drain(_runner())
    return submitted["source_id"], submitted["version_id"]


def test_pending_list_and_detail(real_classification, admin) -> None:
    _, version_id = _submit_pending()
    resp = client.get("/api/v1/admin/classification-pending", cookies=admin)
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert any(i["version_id"] == version_id for i in items)

    detail = client.get(f"/api/v1/admin/classification-pending/{version_id}", cookies=admin)
    assert detail.status_code == 200
    assert detail.json()["data"]["version_id"] == version_id
    assert detail.json()["data"]["classification"]["relevance"] == "UNCERTAIN"


def test_pending_list_requires_admin(real_classification, user) -> None:
    resp = client.get("/api/v1/admin/classification-pending", cookies=user)
    assert resp.status_code == 403


def test_confirm_relevant_creates_chunk_task_and_metadata(real_classification, admin) -> None:
    _, version_id = _submit_pending()
    detail = client.get(f"/api/v1/admin/classification-pending/{version_id}", cookies=admin).json()["data"]
    row_version = detail["row_version"]

    resp = client.post(
        f"/api/v1/admin/classification-pending/{version_id}/confirm-relevant",
        json={
            "expected_row_version": row_version,
            "document_type_code": "operation-manual",
            "product_code": "TDA",
        },
        cookies=admin,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["version_status"] == "PROCESSING"

    # CHUNK 任务已创建
    assert (
        _scalar(
            "SELECT count(*) FROM tasking.processing_tasks WHERE version_id=:vid AND task_type='CHUNK'",
            vid=version_id,
        )
        == 1
    )
    # metadata 落库，人工覆盖字段 MANUAL、其余 MODEL
    with SessionLocal() as session:
        row = session.execute(
            text("SELECT field_sources FROM knowledge.document_metadata WHERE version_id=:vid"),
            {"vid": version_id},
        ).scalar_one()
    assert row["document_type_code"] == "MANUAL"
    assert row["product_code"] == "MANUAL"
    assert row["summary"] == "MODEL"

    # 审计落库
    assert (
        _scalar(
            "SELECT count(*) FROM platform.audit_logs WHERE action='classification.pending.confirm_relevant'"
        )
        == 1
    )


def test_confirm_irrelevant_offlines_source(real_classification, admin) -> None:
    _, version_id = _submit_pending()
    detail = client.get(f"/api/v1/admin/classification-pending/{version_id}", cookies=admin).json()["data"]
    row_version = detail["row_version"]

    resp = client.post(
        f"/api/v1/admin/classification-pending/{version_id}/confirm-irrelevant",
        json={"expected_row_version": row_version, "reason": "人工确认与平台无关"},
        cookies=admin,
    )
    assert resp.status_code == 200, resp.text
    assert (
        _scalar(
            "SELECT s.status FROM knowledge.knowledge_sources s "
            "JOIN knowledge.document_versions v ON v.source_id=s.id WHERE v.id=:vid",
            vid=version_id,
        )
        == "OFFLINE"
    )
    assert (
        _scalar(
            "SELECT s.offline_reason FROM knowledge.knowledge_sources s "
            "JOIN knowledge.document_versions v ON v.source_id=s.id WHERE v.id=:vid",
            vid=version_id,
        )
        == "人工确认与平台无关"
    )


def test_confirm_row_version_conflict(real_classification, admin) -> None:
    _, version_id = _submit_pending()
    resp = client.post(
        f"/api/v1/admin/classification-pending/{version_id}/confirm-irrelevant",
        json={"expected_row_version": 999},  # 过期版本号
        cookies=admin,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "VERSION_CONFLICT"


def test_reclassify_same_config_conflicts(real_classification, admin) -> None:
    _, version_id = _submit_pending()
    resp = client.post(
        f"/api/v1/admin/classification-pending/{version_id}/reclassify",
        json={},
        cookies=admin,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "SAME_INPUT_HASH"


def test_reclassify_after_config_change_creates_task(real_classification, admin) -> None:
    _, version_id = _submit_pending()
    # 发布新的分类配置 revision → 新 input_hash → 允许重分类
    _seed_classification_config(
        {
            "schema_version": "1",
            "thresholds": {"relevant": 0.82, "irrelevant": 0.92},
            "prompt_revision": "2",
        }
    )
    resp = client.post(
        f"/api/v1/admin/classification-pending/{version_id}/reclassify",
        json={},
        cookies=admin,
    )
    assert resp.status_code == 200, resp.text
    # 新分类任务已创建（原 SUCCEEDED + 新 PENDING 共 2 条 CLASSIFY）
    assert (
        _scalar(
            "SELECT count(*) FROM tasking.processing_tasks WHERE version_id=:vid "
            "AND task_type='CLASSIFY' AND status='PENDING'",
            vid=version_id,
        )
        == 1
    )
    assert (
        _scalar(
            "SELECT s.status FROM knowledge.knowledge_sources s "
            "JOIN knowledge.document_versions v ON v.source_id=s.id WHERE v.id=:vid",
            vid=version_id,
        )
        == "PROCESSING"
    )


def test_confirm_requires_admin(real_classification, user) -> None:
    resp = client.post(
        "/api/v1/admin/classification-pending/some-uuid/confirm-relevant",
        json={"expected_row_version": 1},
        cookies=user,
    )
    assert resp.status_code == 403
