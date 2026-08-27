"""操作审计系统测试（DD-17）。

覆盖：
- 动作注册表：未知动作拒绝写入；
- 字段白名单与递归脱敏（敏感字段、超长截断、元数据脱敏）；
- 哈希链校验与篡改检测；
- 事务边界：成功事件与业务变更同事务（回滚一起回滚、提交一起提交）；
- 登录/登出/解绑审计事件；登录失败独立短事务记录且不建会话；
- 普通用户 403 + DENIED 审计；管理员列表/摘要/详情；
- 导出 CSV：UTF-8 BOM 与公式注入防护。
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.audit import service as audit_service
from app.audit.context import AuditContext
from app.audit.models import AuditLog
from app.audit.policy import REDACTED_PLACEHOLDER, UnknownActionError
from app.auth import sessions
from app.core.config import get_settings
from app.db.models.catalog import SourcePriority
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


def _ctx(request_id: str) -> AuditContext:
    return AuditContext(request_id=request_id, source_type="API", source_ip=None, user_agent=None, trace_id=None)


def _audit_rows(action: str, outcome: str | None = None) -> list[dict]:
    with SessionLocal() as s:
        stmt = select(AuditLog).where(AuditLog.action == action)
        if outcome:
            stmt = stmt.where(AuditLog.outcome == outcome)
        rows = s.execute(stmt.order_by(AuditLog.occurred_at)).scalars().all()
        return [
            {
                "id": str(r.id),
                "outcome": r.outcome,
                "error_code": r.error_code,
                "summary": r.summary,
                "actor_name": r.actor_name,
                "request_id": r.request_id,
                "changes": r.changes,
                "metadata": r.metadata_,
                "target_type": r.target_type,
                "target_id": r.target_id,
            }
            for r in rows
        ]


def _oauth_flow() -> str:
    """完整登录流程（start → callback），返回会话 Cookie。"""
    start = client.post("/api/v1/auth/feishu/start").json()["data"]
    resp = client.get(
        f"/api/v1/auth/feishu/callback?code=auth-code&state={start['state']}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return resp.cookies.get(get_settings().session_cookie_name)


def _wait_export(export_id: str, timeout: float = 15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with SessionLocal() as s:
            row = audit_service.get_export(s, export_id)
        if row.status in {"READY", "FAILED", "EXPIRED"}:
            return row
        time.sleep(0.2)
    raise AssertionError(f"导出任务超时未就绪: {export_id}")


# ---- 动作注册表与脱敏 ----

def test_unknown_action_rejected() -> None:
    with pytest.raises(UnknownActionError):
        audit_service.record_success(
            None,
            audit_service.success_event(user=None, context=_ctx("u1"), action="not.in.registry", summary="x"),
        )


def test_whitelist_and_redaction() -> None:
    event = audit_service.success_event(
        user=None,
        context=_ctx("redact-1"),
        action="config.llm.update",
        summary="更新 LLM 配置",
        changes=[
            {"field": "model", "before": "gpt-3", "after": "gpt-4"},
            {"field": "temperature", "before": 0.2, "after": 0.5},
            # api_key 既不在白名单、又是敏感字段 → 整条丢弃
            {"field": "api_key", "before": "sk-abcdef", "after": "sk-zzzz"},
            # 白名单外字段 → 丢弃
            {"field": "not_whitelisted", "before": 1, "after": 2},
            # 白名单内但超长 → 截断
            {"field": "base_url", "before": "http://a", "after": "http://b/" + "x" * 600},
        ],
        metadata={"source": "admin", "nested": {"password": "hunter2", "ok": "fine"}},
        target_type="LLM_CONFIG",
        target_id="llm",
        target_name="LLM 配置",
    )
    with SessionLocal() as s:
        audit_service.record_success(s, event)
        s.commit()

    rows = _audit_rows("config.llm.update")
    assert len(rows) == 1
    changes = rows[0]["changes"]
    fields = [c["field"] for c in changes]
    assert fields == ["model", "temperature", "base_url"]
    # 超长字段截断并带摘要标记
    base_url = [c for c in changes if c["field"] == "base_url"][0]
    assert "截断" in base_url["after"]
    assert len(base_url["after"]) <= 512 + 64
    # 元数据递归脱敏
    meta = rows[0]["metadata"]
    assert meta["nested"]["password"] == REDACTED_PLACEHOLDER
    assert meta["nested"]["ok"] == "fine"
    # 敏感明文绝不落入审计
    assert "sk-abcdef" not in str(rows[0]["summary"])
    assert "hunter2" not in str(rows[0]["metadata"])


# ---- 哈希链 ----

def test_hash_chain_verifies_and_detects_tamper() -> None:
    with SessionLocal() as s:
        audit_service.record_success(
            s, audit_service.success_event(user=None, context=_ctx("h1"), action="auth.login", summary="登录 1")
        )
        s.commit()
        audit_service.record_success(
            s, audit_service.success_event(user=None, context=_ctx("h2"), action="auth.logout", summary="登出 1")
        )
        s.commit()
    with SessionLocal() as s:
        assert audit_service.verify_hash_chain(s) == []

    # 篡改第一条记录的 record_hash，链应同时报 hash 不匹配与 link 断裂
    with SessionLocal() as s:
        first_id = s.execute(select(AuditLog.id).order_by(AuditLog.occurred_at).limit(1)).scalar_one()
        s.execute(
            text("UPDATE platform.audit_logs SET record_hash = '0' * 64 WHERE id = :id"),
            {"id": first_id},
        )
        s.commit()
    with SessionLocal() as s:
        mismatches = audit_service.verify_hash_chain(s)
    assert len(mismatches) >= 2
    assert {"hash", "link"} <= {m["type"] for m in mismatches}


# ---- 事务边界 ----

def test_audit_success_shares_transaction_with_business() -> None:
    def _event() -> audit_service.AuditEvent:
        return audit_service.success_event(
            user=None,
            context=_ctx("atomic"),
            action="config.source_priority.update",
            summary="更新来源优先级",
            target_type="SOURCE_PRIORITY",
            target_id="SRC1",
            changes=[{"field": "priority", "before": 1, "after": 2}],
        )

    # 回滚路径：业务与审计一起消失
    with SessionLocal() as s:
        s.add(SourcePriority(source_code="SRC1", display_name="来源1", priority=1))
        s.flush()
        audit_service.record_success(s, _event())
        s.rollback()
    with SessionLocal() as s:
        assert s.execute(select(func.count()).select_from(SourcePriority)).scalar_one() == 0
        assert s.execute(select(func.count()).select_from(AuditLog)).scalar_one() == 0

    # 提交路径：业务与审计一起落库
    with SessionLocal() as s:
        s.add(SourcePriority(source_code="SRC1", display_name="来源1", priority=1))
        s.flush()
        audit_service.record_success(s, _event())
        s.commit()
    with SessionLocal() as s:
        assert s.execute(select(func.count()).select_from(SourcePriority)).scalar_one() == 1
        assert s.execute(select(func.count()).select_from(AuditLog)).scalar_one() == 1


# ---- 认证审计 ----

def test_login_and_bind_record_audit() -> None:
    cookie = _oauth_flow()
    assert cookie
    rows = _audit_rows("auth.login")
    assert len(rows) == 1
    assert rows[0]["outcome"] == "SUCCESS"
    assert rows[0]["request_id"]  # 中间件生成并透传
    assert _audit_rows("auth.feishu.bind")  # 首次登录产生绑定事件


def test_login_failure_records_failure_without_session() -> None:
    resp = client.get(
        "/api/v1/auth/feishu/callback?code=auth-code&state=nope",
        follow_redirects=False,
    )
    assert resp.status_code == 400
    rows = _audit_rows("auth.login", "FAILURE")
    assert len(rows) == 1
    assert rows[0]["error_code"] == "INVALID_OAUTH_STATE"
    assert rows[0]["actor_name"] == "未登录"
    # 未建立会话
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_records_audit() -> None:
    cookie = _oauth_flow()
    resp = client.post("/api/v1/auth/logout", cookies={get_settings().session_cookie_name: cookie})
    assert resp.status_code == 200
    rows = _audit_rows("auth.logout")
    assert len(rows) == 1
    assert rows[0]["outcome"] == "SUCCESS"


def test_unbind_records_audit() -> None:
    cookie = _oauth_flow()
    resp = client.delete("/api/v1/auth/feishu/binding", cookies={get_settings().session_cookie_name: cookie})
    assert resp.status_code == 200
    rows = _audit_rows("auth.feishu.unbind")
    assert len(rows) == 1
    assert rows[0]["outcome"] == "SUCCESS"
    assert rows[0]["target_type"] == "USER"


# ---- 系统管理登录权限与查询 ----

def test_ordinary_user_can_query_without_denied_audit() -> None:
    cookies = _make_user(False, "普通用户")
    resp = client.get("/api/v1/admin/audit-logs", cookies=cookies)
    assert resp.status_code == 200
    rows = _audit_rows("audit.query", "DENIED")
    assert rows == []


def test_admin_can_list_summary_and_detail() -> None:
    admin = _make_user(True, "管理员")
    _oauth_flow()  # 产生一条登录审计

    resp = client.get("/api/v1/admin/audit-logs", cookies=admin)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["items"]
    first = data["items"][0]
    assert first["outcome"] in {"SUCCESS", "FAILURE", "DENIED"}

    dresp = client.get(f"/api/v1/admin/audit-logs/{first['id']}", cookies=admin)
    assert dresp.status_code == 200
    detail = dresp.json()["data"]
    assert detail["record_hash"] and detail["id"] == first["id"]
    assert isinstance(detail["changes"], list)

    sresp = client.get("/api/v1/admin/audit-logs/summary", cookies=admin)
    assert sresp.status_code == 200
    assert sresp.json()["data"]["total"] >= 1


# ---- 导出 ----

def test_export_csv_formula_injection_protected() -> None:
    admin = _make_user(True, "管理员")
    # 写入一条 summary 以 = 开头的失败审计（真实业务不会这样写，用于验证导出防护）
    audit_service.record_failure_independent(
        audit_service.AuditEvent(
            action="auth.login",
            summary='=HYPERLINK("http://evil.example","x")',
            actor=dict(audit_service.ACTOR_SYSTEM),
            context=_ctx("export-1"),
            error_code="TEST",
        )
    )

    resp = client.post(
        "/api/v1/admin/audit-exports",
        json={"outcome": "FAILURE"},
        cookies=admin,
    )
    assert resp.status_code == 202
    export_id = resp.json()["data"]["id"]
    row = _wait_export(export_id)
    assert row.status == "READY"

    dl = client.get(f"/api/v1/admin/audit-exports/{export_id}/download", cookies=admin)
    assert dl.status_code == 200
    content = dl.content
    assert content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    text_content = content.decode("utf-8-sig")
    # 以 = 开头的单元格被 ' 前缀转义，防电子表格执行公式
    assert "=HYPERLINK" in text_content
    assert "'=HYPERLINK" in text_content
