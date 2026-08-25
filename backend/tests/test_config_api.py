"""目录/知识库配置与 LLM 配置 API 测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import sessions
from app.core.config import get_settings
from app.db.models.user import User
from app.db.session import SessionLocal
from app.main import app


client = TestClient(app)


def _make_user(is_admin: bool, display_name: str) -> dict:
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
    return _make_user(True, "管理员")


@pytest.fixture()
def user() -> dict:
    return _make_user(False, "普通用户")


def _create_product(admin: dict, code="prod-a", name="产品A") -> dict:
    resp = client.post("/api/v1/admin/catalog/products", json={"code": code, "name": name}, cookies=admin)
    assert resp.status_code in (201,), resp.text
    return resp.json()["data"]


# ---- catalog 查询（public，仅启用态） ----

def test_catalog_returns_only_enabled(admin: dict) -> None:
    p = _create_product(admin, "cat-on", "启用产品")
    _create_product(admin, "cat-off", "停用产品")
    # 停用 cat-on，catalog 只应返回启用的 cat-off
    client.post(f"/api/v1/admin/catalog/products/{p['id']}/disable", cookies=admin)

    resp = client.get("/api/v1/catalog/products")
    items = resp.json()["data"]["items"]
    assert [i["code"] for i in items] == ["cat-off"]


def test_catalog_requires_no_auth() -> None:
    assert client.get("/api/v1/catalog/products").status_code == 200
    assert client.get("/api/v1/catalog/document-types").status_code == 200
    assert client.get("/api/v1/catalog/product-forms").status_code == 200


# ---- 管理员权限 ----

def test_admin_endpoints_require_admin(user: dict) -> None:
    assert client.get("/api/v1/admin/catalog/products", cookies=user).status_code == 403
    assert client.get("/api/v1/admin/llm-config", cookies=user).status_code == 403
    assert client.get("/api/v1/admin/source-priorities", cookies=user).status_code == 403
    assert client.get("/api/v1/admin/catalog/products").status_code == 401  # 未登录


# ---- 产品 CRUD 与约束 ----

def test_product_code_unique(admin: dict) -> None:
    _create_product(admin, "dup-code", "产品1")
    resp = client.post("/api/v1/admin/catalog/products", json={"code": "dup-code", "name": "产品2"}, cookies=admin)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "DUPLICATE_CODE"


def test_product_disable_blocks_new_version(admin: dict) -> None:
    p = _create_product(admin, "blocked-prod", "停用产品")
    client.post(f"/api/v1/admin/catalog/products/{p['id']}/disable", cookies=admin)
    resp = client.post(
        f"/api/v1/admin/catalog/products/{p['id']}/versions",
        json={"version_code": "1.0", "major_version": 1, "minor_version": 0},
        cookies=admin,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "PRODUCT_DISABLED"


def test_version_disable_excluded_from_catalog(admin: dict) -> None:
    p = _create_product(admin, "ver-prod", "版本产品")
    v = client.post(
        f"/api/v1/admin/catalog/products/{p['id']}/versions",
        json={"version_code": "2.0", "major_version": 2, "minor_version": 0},
        cookies=admin,
    ).json()["data"]
    client.post(f"/api/v1/admin/catalog/versions/{v['id']}/disable", cookies=admin)

    resp = client.get(f"/api/v1/catalog/products/{p['id']}/versions")
    assert resp.json()["data"]["items"] == []


def test_update_concurrency_conflict(admin: dict) -> None:
    p = _create_product(admin, "concurrent", "并发产品")
    resp = client.patch(
        f"/api/v1/admin/catalog/products/{p['id']}",
        json={"name": "新名字", "row_version": 99},
        cookies=admin,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "VERSION_CONFLICT"


# ---- 来源优先级 ----

def _seed_source_priorities() -> None:
    from app.db.models.catalog import SourcePriority

    with SessionLocal() as s:
        for code, name, prio in [
            ("MANUAL_UPLOAD", "手工上传", 10),
            ("FEISHU_WIKI", "飞书知识库", 20),
            ("FEISHU_DOC", "飞书文档", 30),
            ("SEG_CASE", "SEG 问题案件", 40),
        ]:
            s.add(SourcePriority(source_code=code, display_name=name, priority=prio))
        s.commit()


def test_source_priorities_update(admin: dict) -> None:
    _seed_source_priorities()
    resp = client.patch(
        "/api/v1/admin/source-priorities",
        json={"items": [{"source_code": "MANUAL_UPLOAD", "priority": 5}, {"source_code": "FEISHU_DOC", "priority": 6}]},
        cookies=admin,
    )
    assert resp.status_code == 200
    by_code = {i["source_code"]: i["priority"] for i in resp.json()["data"]["items"]}
    assert by_code["MANUAL_UPLOAD"] == 5
    assert by_code["FEISHU_DOC"] == 6


def test_source_priorities_duplicate_priority_rejected(admin: dict) -> None:
    resp = client.patch(
        "/api/v1/admin/source-priorities",
        json={"items": [{"source_code": "MANUAL_UPLOAD", "priority": 5}, {"source_code": "FEISHU_DOC", "priority": 5}]},
        cookies=admin,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "DUPLICATE_PRIORITY"


# ---- LLM 配置 ----

def test_llm_config_api_key_not_exposed(admin: dict) -> None:
    initial = client.get("/api/v1/admin/llm-config", cookies=admin).json()["data"]
    assert initial["has_api_key"] is False

    payload = {
        "provider": "openai-compatible",
        "base_url": "http://localhost:9999/v1",
        "model": "test-model",
        "temperature": 0.2,
        "top_p": 1.0,
        "max_tokens": 2048,
        "timeout_seconds": 60,
        "classification_model": "",
        "embedding_model": "",
        "enabled": True,
        "api_key": "sk-secret-123",
    }
    resp = client.put("/api/v1/admin/llm-config", json=payload, cookies=admin)
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["has_api_key"] is True
    assert "sk-secret-123" not in resp.text
    assert "api_key" not in body

    from sqlalchemy import text as sa_text

    with SessionLocal() as s:
        ct = s.execute(
            sa_text("SELECT ciphertext FROM platform.secret_values WHERE namespace='llm' AND key_name='api_key'")
        ).scalar_one()
    assert b"sk-secret-123" not in bytes(ct)


def test_llm_config_clear_api_key(admin: dict) -> None:
    payload = {
        "base_url": "http://localhost:9999/v1", "model": "m",
        "provider": "openai-compatible", "temperature": 0.2, "top_p": 1.0,
        "max_tokens": 2048, "timeout_seconds": 60,
        "classification_model": "", "embedding_model": "", "enabled": False,
        "api_key": "sk-tmp",
    }
    client.put("/api/v1/admin/llm-config", json=payload, cookies=admin)
    clear = {**payload, "api_key": ""}
    resp = client.put("/api/v1/admin/llm-config", json=clear, cookies=admin)
    assert resp.json()["data"]["has_api_key"] is False
