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


# ---- 文档类型正式目录（DD-19 Phase 1） ----

# 12 类稳定 code 与排序：与迁移 eb6fca22ccd9、前端 QueryComposer 保持一致（AC-CLS-001）。
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


def _seed_document_types() -> None:
    from app.db.models.catalog import DocumentType

    with SessionLocal() as s:
        for code, name, sort_order in BASELINE_DOCUMENT_TYPES:
            s.add(DocumentType(code=code, name=name, sort_order=sort_order))
        s.commit()


def test_catalog_document_types_baseline(admin: dict) -> None:
    """前后端和数据库使用同一套 12 类稳定 code，按 sort_order 返回且全部启用态。"""
    _seed_document_types()
    resp = client.get("/api/v1/catalog/document-types")
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert [(i["code"], i["name"], i["sort_order"], i["status"]) for i in items] == [
        (code, name, sort_order, "ENABLED") for code, name, sort_order in BASELINE_DOCUMENT_TYPES
    ]


def test_catalog_document_types_exclude_disabled(admin: dict) -> None:
    """停用的文档类型不进入查询目录，且顺序仍按 sort_order 升序。"""
    _seed_document_types()
    resp_types = client.get("/api/v1/admin/catalog/document-types", cookies=admin)
    other_id = next(i["id"] for i in resp_types.json()["data"]["items"] if i["code"] == "other")
    assert client.post(f"/api/v1/admin/catalog/document-types/{other_id}/disable", cookies=admin).status_code == 200

    resp = client.get("/api/v1/catalog/document-types")
    items = resp.json()["data"]["items"]
    codes = [i["code"] for i in items]
    assert "other" not in codes
    assert codes == [code for code, _, _ in BASELINE_DOCUMENT_TYPES if code != "other"]
    sorts = [i["sort_order"] for i in items]
    assert sorts == sorted(sorts)


# ---- 系统管理登录权限 ----

def test_admin_endpoints_require_login_but_not_admin(user: dict) -> None:
    assert client.get("/api/v1/admin/catalog/products", cookies=user).status_code == 200
    assert client.get("/api/v1/admin/llm-config/models", cookies=user).status_code == 200
    assert client.get("/api/v1/admin/llm-config/service-bindings", cookies=user).status_code == 200
    assert client.get("/api/v1/admin/source-priorities", cookies=user).status_code == 200
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
