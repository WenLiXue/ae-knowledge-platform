"""LLM 模型管理与服务配置 API 测试（DD-20 §14.1 TC-MC-001~012）。"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import sessions, crypto
from app.core.config import get_settings
from app.db.models.config import ConfigRevision, SecretValue
from app.db.models.user import User
from app.db.session import SessionLocal
from app.llm import migration as llm_migration
from app.llm import service as llm_service
from app.main import app


client = TestClient(app)


def _make_user(is_admin: bool, display_name: str = "管理员") -> dict:
    with SessionLocal() as s:
        user = User(display_name=display_name, status="ACTIVE", is_admin=is_admin, created_source="ADMIN")
        s.add(user)
        s.commit()
        s.refresh(user)
        token = sessions.create_session(s, user.id, 24)
        s.commit()
        return {get_settings().session_cookie_name: token}


@pytest.fixture()
def admin() -> dict:
    return _make_user(True)


def _model_payload(**overrides) -> dict:
    payload = {
        "name": "内网 Qwen",
        "model_type": "CHAT",
        "provider": "openai-compatible",
        "base_url": "http://localhost:9999/v1",
        "model_name": "Qwen3-32B",
        "enabled": True,
        "expected_revision": None,
    }
    payload.update(overrides)
    return payload


def _create_chat(admin: dict, name: str = "内网 Qwen", **overrides) -> dict:
    resp = client.post("/api/v1/admin/llm-config/models", json=_model_payload(name=name, **overrides), cookies=admin)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _revision(admin: dict) -> int | None:
    return client.get("/api/v1/admin/llm-config/models", cookies=admin).json()["data"]["revision"]


# ---- TC-MC-001 新增 CHAT 模型 ----

def test_create_model_returns_id_revision_grows_key_not_echoed(admin: dict) -> None:
    rev0 = _revision(admin)
    model = _create_chat(admin, api_key="sk-secret-123")
    assert model["id"]
    assert model["model_type"] == "CHAT"
    assert model["has_api_key"] is True
    assert model["base_url"] == "http://localhost:9999/v1"
    assert "sk-secret-123" not in client.get("/api/v1/admin/llm-config/models", cookies=admin).text
    rev1 = _revision(admin)
    assert rev1 is not None and rev1 != rev0


# ---- TC-MC-001b 自定义服务商标签可被接受（DD-20 §6.2 受控枚举，不硬编码客户名称） ----

def test_create_model_custom_provider_label(admin: dict) -> None:
    model = _create_chat(admin, name="亚信", provider="asiainfo-sec")
    assert model["provider"] == "asiainfo-sec"
    # 空服务商被拒绝
    resp = client.post("/api/v1/admin/llm-config/models", json=_model_payload(name="空商", provider=""), cookies=admin)
    assert resp.status_code == 422


# ---- TC-MC-002 编辑模型 api_key=null 保持密钥 ----

def test_update_model_api_key_null_keeps_key(admin: dict) -> None:
    model = _create_chat(admin, api_key="sk-keep")
    resp = client.patch(
        f"/api/v1/admin/llm-config/models/{model['id']}",
        json={"name": "改名", "expected_revision": _revision(admin)},
        cookies=admin,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "改名"
    assert resp.json()["data"]["has_api_key"] is True

    with SessionLocal() as s:
        assert llm_service._get_secret(s, model["id"]) == "sk-keep"


# ---- TC-MC-003 同名模型重复新增 ----

def test_create_model_duplicate_name_rejected(admin: dict) -> None:
    _create_chat(admin)
    rev_before = _revision(admin)
    resp = client.post("/api/v1/admin/llm-config/models", json=_model_payload(name="内网 Qwen"), cookies=admin)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "MODEL_CONFIG_NAME_DUPLICATE"
    assert _revision(admin) == rev_before


# ---- TC-MC-004/005 停用未引用 / 已引用模型 ----

def test_disable_unreferenced_model(admin: dict) -> None:
    model = _create_chat(admin)
    resp = client.post(f"/api/v1/admin/llm-config/models/{model['id']}/disable", cookies=admin)
    assert resp.status_code == 200
    assert resp.json()["data"]["enabled"] is False


def test_disable_referenced_model_blocked(admin: dict) -> None:
    chat = _create_chat(admin, name="问答模型")
    rev = _revision(admin)
    resp = client.put(
        "/api/v1/admin/llm-config/service-bindings",
        json={"expected_revision": rev, "bindings": {"QA": chat["id"], "DOCUMENT_CLASSIFICATION": None, "DOCUMENT_EMBEDDING": None, "RETRIEVAL_RERANK": None}},
        cookies=admin,
    )
    assert resp.status_code == 200
    resp = client.post(f"/api/v1/admin/llm-config/models/{chat['id']}/disable", cookies=admin)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "MODEL_CONFIG_IN_USE"


# ---- TC-MC-006/007/008 服务绑定校验 ----

def test_bind_qa_chat_ok(admin: dict) -> None:
    chat = _create_chat(admin)
    rev = _revision(admin)
    resp = client.put(
        "/api/v1/admin/llm-config/service-bindings",
        json={"expected_revision": rev, "bindings": {"QA": chat["id"], "DOCUMENT_CLASSIFICATION": chat["id"], "DOCUMENT_EMBEDDING": None, "RETRIEVAL_RERANK": None}},
        cookies=admin,
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    qa = next(s for s in body["services"] if s["service_type"] == "QA")
    assert qa["model"]["id"] == chat["id"]


def test_bind_type_mismatch_keeps_all_bindings(admin: dict) -> None:
    chat = _create_chat(admin, name="问答模型")
    embed = _create_chat(admin, name="向量模型", model_type="EMBEDDING", model_name="bge-m3")
    rev = _revision(admin)
    ok = client.put(
        "/api/v1/admin/llm-config/service-bindings",
        json={"expected_revision": rev, "bindings": {"QA": chat["id"], "DOCUMENT_CLASSIFICATION": None, "DOCUMENT_EMBEDDING": embed["id"], "RETRIEVAL_RERANK": None}},
        cookies=admin,
    )
    assert ok.status_code == 200

    rev2 = ok.json()["data"]["revision"]
    resp = client.put(
        "/api/v1/admin/llm-config/service-bindings",
        json={"expected_revision": rev2, "bindings": {"QA": embed["id"], "DOCUMENT_CLASSIFICATION": None, "DOCUMENT_EMBEDDING": embed["id"], "RETRIEVAL_RERANK": None}},
        cookies=admin,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "MODEL_TYPE_MISMATCH"
    body = client.get("/api/v1/admin/llm-config/service-bindings", cookies=admin).json()["data"]
    qa = next(s for s in body["services"] if s["service_type"] == "QA")
    assert qa["model"]["id"] == chat["id"]  # 全部绑定不变


def test_bind_disabled_model_blocked(admin: dict) -> None:
    chat = _create_chat(admin, name="停用模型")
    client.post(f"/api/v1/admin/llm-config/models/{chat['id']}/disable", cookies=admin)
    resp = client.put(
        "/api/v1/admin/llm-config/service-bindings",
        json={"expected_revision": _revision(admin), "bindings": {"QA": chat["id"], "DOCUMENT_CLASSIFICATION": None, "DOCUMENT_EMBEDDING": None, "RETRIEVAL_RERANK": None}},
        cookies=admin,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "MODEL_CONFIG_DISABLED"


# ---- TC-MC-009 revision 冲突 ----

def test_stale_revision_conflict(admin: dict) -> None:
    _create_chat(admin)
    stale_rev = _revision(admin)  # 当前 revision
    _create_chat(admin, name="另一模型")  # 使 revision 前进
    resp = client.post(
        "/api/v1/admin/llm-config/models",
        json=_model_payload(name="第三模型", expected_revision=stale_rev),
        cookies=admin,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "CONFIG_VERSION_CONFLICT"


# ---- TC-MC-010 GET 不泄露密钥 ----

def test_list_models_no_secret(admin: dict) -> None:
    _create_chat(admin, api_key="sk-topsecret")
    resp = client.get("/api/v1/admin/llm-config/models", cookies=admin)
    assert resp.status_code == 200
    assert "sk-topsecret" not in resp.text
    for item in resp.json()["data"]["items"]:
        assert "api_key" not in item
        assert item["has_api_key"] is True


# ---- TC-MC-011 三种类型连接测试 ----

@pytest.fixture()
def mock_httpx(monkeypatch):
    """用 httpx.MockTransport 拦截 service 层的默认 HTTP 客户端工厂。"""

    def _install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(llm_service, "_default_client", lambda *a, **k: httpx.Client(transport=transport))

    return _install


def test_test_chat_success(admin: dict, mock_httpx) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer sk-test"
        body = json.loads(request.content)
        assert body["messages"][0]["content"] == "ping"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    mock_httpx(handler)
    resp = client.post(
        "/api/v1/admin/llm-config/models/test",
        json={"model_type": "CHAT", "provider": "openai-compatible", "base_url": "http://localhost:9999/v1", "model_name": "m", "api_key": "sk-test"},
        cookies=admin,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["ok"] is True


def test_test_embedding_returns_dimension(admin: dict, mock_httpx) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3]}]})

    mock_httpx(handler)
    resp = client.post(
        "/api/v1/admin/llm-config/models/test",
        json={"model_type": "EMBEDDING", "provider": "openai-compatible", "base_url": "http://localhost:9999/v1", "model_name": "bge-m3", "api_key": "sk-test"},
        cookies=admin,
    )
    assert resp.json()["data"]["ok"] is True
    assert resp.json()["data"]["dimension"] == 3


def test_test_rerank_success(admin: dict, mock_httpx) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rerank")
        return httpx.Response(200, json={"results": [{"index": 0, "score": 0.9}]})

    mock_httpx(handler)
    resp = client.post(
        "/api/v1/admin/llm-config/models/test",
        json={"model_type": "RERANK", "provider": "openai-compatible", "base_url": "http://localhost:9999/v1", "model_name": "rerank-m", "api_key": "sk-test"},
        cookies=admin,
    )
    assert resp.json()["data"]["ok"] is True


def test_test_error_mapping(admin: dict, mock_httpx) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/auth" in path:
            return httpx.Response(401, json={"error": "unauthorized"})
        if "/notfound" in path:
            return httpx.Response(404, json={"error": "nope"})
        if "/timeout" in path:
            raise httpx.ReadTimeout("slow")
        raise httpx.ConnectError("refused")

    mock_httpx(handler)
    for suffix, code in [("/auth", "MODEL_TEST_AUTH_FAILED"), ("/notfound", "MODEL_TEST_NOT_FOUND"), ("/timeout", "MODEL_TEST_TIMEOUT"), ("/net", "MODEL_TEST_NETWORK_ERROR")]:
        resp = client.post(
            "/api/v1/admin/llm-config/models/test",
            json={"model_type": "CHAT", "provider": "openai-compatible", "base_url": f"http://localhost:9999{suffix}", "model_name": "m", "api_key": "sk-test"},
            cookies=admin,
        )
        assert resp.json()["data"]["ok"] is False
        assert code in resp.json()["data"]["message"]


# ---- TC-MC-012 旧配置迁移幂等 ----

def _seed_legacy_config() -> None:
    key = get_settings().token_enc_key
    with SessionLocal() as s:
        s.add(
            ConfigRevision(
                namespace="llm",
                content={
                    "provider": "openai-compatible",
                    "base_url": "http://localhost:9999/v1/",
                    "model": "Qwen-32B",
                    "classification_model": "Qwen-32B",
                    "embedding_model": "bge-m3",
                    "enabled": True,
                },
                status="ACTIVE",
            )
        )
        s.add(
            SecretValue(
                namespace="llm",
                key_name="api_key",
                ciphertext=crypto.encrypt("sk-old-key", key),
                key_version="1",
            )
        )
        s.commit()


def test_legacy_migration_idempotent(admin: dict) -> None:
    _seed_legacy_config()
    with SessionLocal() as s:
        assert llm_migration.ensure_llm_schema_v2(s, user_id=None) is True
        s.commit()
        # 二次执行 no-op
        assert llm_migration.ensure_llm_schema_v2(s, user_id=None) is False
        s.commit()

    from sqlalchemy import select as sa_select

    with SessionLocal() as s:
        rows = s.execute(sa_select(ConfigRevision).where(ConfigRevision.namespace == "llm").order_by(ConfigRevision.id)).scalars().all()
    assert len(rows) == 2  # 1 旧(RETIRED) + 1 新(ACTIVE)
    active = next(r for r in rows if r.status == "ACTIVE")
    content = active.content
    assert content["schema_version"] == 2
    # classification_model 同名同 Endpoint → 复用 QA 的 CHAT 模型，共 2 个模型
    assert len(content["models"]) == 2
    assert content["service_bindings"]["QA"] is not None
    assert content["service_bindings"]["DOCUMENT_CLASSIFICATION"] == content["service_bindings"]["QA"]
    assert content["service_bindings"]["RETRIEVAL_RERANK"] is None

    # 密钥已复制到模型 SecretValue，旧 llm/api_key 已删除
    with SessionLocal() as s:
        from sqlalchemy import text as sa_text

        old = s.execute(sa_text("SELECT count(*) FROM platform.secret_values WHERE namespace='llm' AND key_name='api_key'")).scalar_one()
        assert old == 0
        for m in content["models"]:
            assert llm_service._get_secret(s, m["id"]) == "sk-old-key"

    # 迁移后 API 正常读取
    resp = client.get("/api/v1/admin/llm-config/models", cookies=admin)
    assert resp.status_code == 200
    assert len(resp.json()["data"]["items"]) == 2


# ---- 运行时解析器 ----

def test_runtime_resolver(admin: dict) -> None:
    chat = _create_chat(admin, name="问答模型", api_key="sk-runtime")
    rev = _revision(admin)
    client.put(
        "/api/v1/admin/llm-config/service-bindings",
        json={"expected_revision": rev, "bindings": {"QA": chat["id"], "DOCUMENT_CLASSIFICATION": None, "DOCUMENT_EMBEDDING": None, "RETRIEVAL_RERANK": None}},
        cookies=admin,
    )
    from app.llm.runtime import resolve_service_model

    with SessionLocal() as s:
        resolved = resolve_service_model(s, "QA")
        assert resolved is not None
        assert resolved.model_config_id == chat["id"]
        assert resolved.api_key == "sk-runtime"
        # 可选服务未配置返回 None
        assert resolve_service_model(s, "RETRIEVAL_RERANK") is None
