"""飞书 OAuth 与用户绑定测试。

覆盖：Fake OAuth 端到端（start → callback → 绑定 → 会话 → me → 携带 token 发现）、
token 过期刷新/刷新失败返回 None、未授权 401、凭据密文非明文、
Real OAuth 错误映射（httpx.MockTransport）。
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import feishu as auth_feishu
from app.auth import service
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.feishu_auth.fake import FakeFeishuOAuthClient
from app.feishu_auth.real import RealFeishuOAuthClient
from app.feishu_provider.base import AUTH, RATE_LIMIT, TIMEOUT, FeishuError
from app.main import app


client = TestClient(app)
KEY = get_settings().token_enc_key


def _oauth_callback(code: str, state: str):
    # follow_redirects=False 以读取 Set-Cookie
    return client.get(
        f"/api/v1/auth/feishu/callback?code={code}&state={state}", follow_redirects=False
    )


def test_oauth_flow_binds_user_and_sets_session() -> None:
    # 1. start：创建 state，返回授权 URL
    start = client.post("/api/v1/auth/feishu/start")
    assert start.status_code == 200
    data = start.json()["data"]
    assert data["state"]
    assert "passport.feishu.cn" in data["authorize_url"]

    # 2. callback：换码、绑定、设会话 Cookie
    resp = _oauth_callback("auth-code", data["state"])
    assert resp.status_code == 302
    assert resp.headers.get("location") == get_settings().feishu_frontend_redirect_uri
    assert resp.cookies.get(get_settings().session_cookie_name)

    # 3. /auth/me：当前用户已绑定飞书
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    body = me.json()["data"]
    assert body["feishu_bound"] is True
    assert body["display_name"] == "Fake 用户"

    # 4. 携带会话调用发现接口（Fake provider 忽略 token，链路可用）
    docs = client.get("/api/v1/feishu/documents")
    assert docs.status_code == 200

    # 5. 绑定身份与凭据落库；凭据为密文，不含明文 token
    with SessionLocal() as s:
        n_id = s.execute(text("SELECT count(*) FROM auth.external_identities")).scalar_one()
        n_cred = s.execute(text("SELECT count(*) FROM auth.external_credentials")).scalar_one()
        ct = s.execute(text("SELECT access_token_ciphertext FROM auth.external_credentials")).scalar_one()
        assert n_id == 1 and n_cred == 1
        assert b"fake-access-token" not in bytes(ct)


def test_oauth_callback_rejects_invalid_state() -> None:
    resp = _oauth_callback("auth-code", "state-does-not-exist")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "INVALID_OAUTH_STATE"
    # 未建立会话
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 401


def test_me_requires_login() -> None:
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_same_feishu_identity_logs_in_same_user() -> None:
    start = client.post("/api/v1/auth/feishu/start").json()["data"]
    _oauth_callback("auth-code", start["state"])
    first = client.get("/api/v1/auth/me").json()["data"]

    client.post("/api/v1/auth/logout")
    start2 = client.post("/api/v1/auth/feishu/start").json()["data"]
    _oauth_callback("auth-code", start2["state"])
    second = client.get("/api/v1/auth/me").json()["data"]

    assert second["user_id"] == first["user_id"]
    with SessionLocal() as s:
        n = s.execute(text("SELECT count(*) FROM auth.external_identities")).scalar_one()
    assert n == 1  # 不重复创建身份/用户


def test_token_refresh_when_expired() -> None:
    oauth = FakeFeishuOAuthClient()
    with SessionLocal() as s:
        data = service.start_oauth(s, oauth, "http://cb")
        user = service.process_oauth_callback(s, oauth, "code", data["state"], KEY).user
        # 手动把 access token 置为过期
        s.execute(
            text("UPDATE auth.external_credentials SET access_expires_at = now() - interval '1 hour'")
        )
        s.commit()
        # 过期后 get_user_access_token 应刷新并返回新 token
        token = auth_feishu.get_user_access_token(s, user.id, oauth, KEY)
        assert token == "fake-access-token-2"
        assert oauth.refresh_calls == 1


def test_token_refresh_failure_returns_none() -> None:
    oauth = FakeFeishuOAuthClient()
    oauth.refresh_should_fail = True
    with SessionLocal() as s:
        data = service.start_oauth(s, oauth, "http://cb")
        user = service.process_oauth_callback(s, oauth, "code", data["state"], KEY).user
        s.execute(
            text("UPDATE auth.external_credentials SET access_expires_at = now() - interval '1 hour'")
        )
        s.commit()
        assert auth_feishu.get_user_access_token(s, user.id, oauth, KEY) is None


def test_unbind_feishu_keeps_user() -> None:
    start = client.post("/api/v1/auth/feishu/start").json()["data"]
    _oauth_callback("auth-code", start["state"])

    unbind = client.delete("/api/v1/auth/feishu/binding")
    assert unbind.status_code == 200
    me = client.get("/api/v1/auth/me").json()["data"]
    assert me["feishu_bound"] is False
    # 绑定用户仍在（系统默认用户 + 该用户）
    with SessionLocal() as s:
        n = s.execute(text("SELECT count(*) FROM auth.users")).scalar_one()
    assert n == 2


# ---- Real OAuth 错误映射（httpx.MockTransport，不联调真实飞书） ----


def _real_oauth(handler) -> RealFeishuOAuthClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return RealFeishuOAuthClient(app_id="app", app_secret="secret", http_client=http)


def test_real_oauth_build_authorize_url() -> None:
    oauth = _real_oauth(lambda req: httpx.Response(200, json={"code": 0, "data": {}}))
    url = oauth.build_authorize_url("s1", "https://cb/x")
    assert "passport.feishu.cn" in url
    assert "client_id=app" in url
    assert "state=s1" in url
    assert "redirect_uri=https%3A%2F%2Fcb%2Fx" in url


def test_real_oauth_error_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("app_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t", "expire": 7200})
        import json as _json

        body = _json.loads(request.content or b"{}")
        code = body.get("code", "ok")
        if code == "auth-fail":
            return httpx.Response(200, json={"code": 99991664, "msg": "auth expired", "data": {}})
        if code == "rate":
            return httpx.Response(200, json={"code": 910002, "msg": "rate limited", "data": {}})
        return httpx.Response(200, json={"code": 0, "data": {"access_token": "a", "refresh_token": "r", "token_type": "Bearer", "expires_in": 7200}})

    oauth = _real_oauth(handler)

    with pytest.raises(FeishuError) as excinfo:
        oauth.exchange_code("auth-fail")
    assert excinfo.value.category == AUTH
    assert excinfo.value.retryable is False

    with pytest.raises(FeishuError) as excinfo:
        oauth.exchange_code("rate")
    assert excinfo.value.category == RATE_LIMIT
    assert excinfo.value.retryable is True

    bundle = oauth.exchange_code("ok")
    assert bundle.access_token == "a"


def test_real_oauth_http_status_and_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("app_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t", "expire": 7200})
        raise httpx.ReadTimeout("timeout")

    oauth = _real_oauth(handler)

    with pytest.raises(FeishuError) as excinfo:
        oauth.get_user_info("tok", "Bearer")
    assert excinfo.value.category == TIMEOUT
    assert excinfo.value.retryable is True


def test_credential_roundtrip() -> None:
    from app.auth.crypto import decrypt, encrypt

    ct = encrypt("secret-token", KEY)
    assert decrypt(ct, KEY) == "secret-token"
    # 密文不含明文
    assert b"secret-token" not in bytes(ct)
