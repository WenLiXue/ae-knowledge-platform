"""RealFeishuOAuthClient：基于已验证的官方示例契约实现飞书扫码/授权码登录。

端点契约（来源：飞书官方扫码登录示例 qr_login_python / qr_login_react，已验证可用）：
- 授权 URL：{passport_host}authorize?client_id={app_id}&redirect_uri={encoded}&response_type=code&state={state}
- app/tenant token：POST {base}/open-apis/auth/v3/app_access_token/internal，body {app_id, app_secret} → data.tenant_access_token
- 换码：POST {base}/open-apis/authen/v1/oidc/access_token，Authorization: Bearer {tenant_token}，body {grant_type:"authorization_code", code}
- 用户信息：GET {base}/open-apis/authen/v1/user_info，Authorization: {token_type} {access_token}
- 刷新：POST {base}/open-apis/authen/v1/refresh_access_token，Authorization: Bearer {tenant_token}，body {grant_type:"refresh_token", refresh_token}

app_id / app_secret 只从构造参数读取（配置/环境变量），永不进入日志与响应。
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import httpx

from ..core.logging import log_external_call
from ..feishu_provider.base import AUTH, RATE_LIMIT, TIMEOUT, TRANSIENT, FeishuError
from .base import FeishuOAuthClient, FeishuTokenBundle, FeishuUserProfile

_OAUTH_ERROR_CODE_MAP: dict[int, str] = {
    910002: RATE_LIMIT,
    99991663: AUTH,
    99991664: AUTH,
    99991665: AUTH,
}


class RealFeishuOAuthClient(FeishuOAuthClient):
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        base_url: str = "https://open.feishu.cn",
        passport_host: str = "https://passport.feishu.cn/suite/passport/oauth/",
        timeout_seconds: float = 10.0,
        http_client: httpx.Client | None = None,
    ):
        self._app_id = app_id
        self._app_secret = app_secret
        self._base_url = base_url.rstrip("/")
        self._passport_host = passport_host.rstrip("/") + "/"
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds), follow_redirects=True
        )
        self._app_token: str | None = None
        self._app_token_expires_at: float = 0.0

    def _app_access_token(self) -> str:
        if self._app_token and time.time() < self._app_token_expires_at:
            return self._app_token
        # 该接口的 tenant_access_token 在响应顶层，不在 data 内（官方示例如此读取）
        body = self._request(
            "POST", "/open-apis/auth/v3/app_access_token/internal",
            headers={},
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        token = body.get("tenant_access_token", "")
        expire = body.get("expire", 7200)
        self._app_token = token
        self._app_token_expires_at = time.time() + expire - 60
        return token

    def build_authorize_url(self, state: str, redirect_uri: str) -> str:
        query = (
            f"client_id={quote(self._app_id, safe='')}"
            f"&redirect_uri={quote(redirect_uri, safe='')}"
            f"&response_type=code&state={quote(state, safe='')}"
        )
        return f"{self._passport_host}authorize?{query}"

    def exchange_code(self, code: str) -> FeishuTokenBundle:
        body = self._request(
            "POST", "/open-apis/authen/v1/oidc/access_token",
            headers={"Authorization": f"Bearer {self._app_access_token()}"},
            json={"grant_type": "authorization_code", "code": code},
        )
        return _bundle_from_data(body.get("data", {}))

    def get_user_info(self, access_token: str, token_type: str) -> FeishuUserProfile:
        body = self._request(
            "GET", "/open-apis/authen/v1/user_info",
            headers={"Authorization": f"{token_type} {access_token}"},
        )
        data = body.get("data", {})
        return FeishuUserProfile(
            open_id=data.get("open_id", ""),
            tenant_key=data.get("tenant_key", ""),
            union_id=data.get("union_id"),
            user_id=data.get("user_id"),
            name=data.get("name"),
            avatar_url=data.get("avatar_url"),
        )

    def refresh_access_token(self, refresh_token: str) -> FeishuTokenBundle:
        body = self._request(
            "POST", "/open-apis/authen/v1/refresh_access_token",
            headers={"Authorization": f"Bearer {self._app_access_token()}"},
            json={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        return _bundle_from_data(body.get("data", {}))

    # ---- 统一请求与错误映射 ----

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        req_headers = {"Content-Type": "application/json", **headers}
        url = f"{self._base_url}{path}"
        start = time.perf_counter()
        status_code: int | None = None
        result = "ok"
        try:
            try:
                resp = self._http.request(method, url, headers=req_headers, json=json, params=params)
                status_code = resp.status_code
            except httpx.TimeoutException as exc:
                result = "timeout"
                raise FeishuError(TIMEOUT, "FEISHU_TIMEOUT", f"飞书接口超时: {path}", retryable=True) from exc
            except httpx.HTTPError as exc:
                result = "network_error"
                raise FeishuError(TRANSIENT, "FEISHU_NETWORK", f"飞书网络错误: {exc}", retryable=True) from exc

            if resp.status_code == 429:
                result = "rate_limited"
                raise FeishuError(RATE_LIMIT, "FEISHU_RATE_LIMITED", "飞书接口限流", retryable=True)
            if resp.status_code in (401, 403):
                result = "auth_expired"
                raise FeishuError(AUTH, "FEISHU_AUTH_EXPIRED", "飞书授权失效", retryable=False)

            try:
                body = resp.json()
            except ValueError:
                result = "bad_json"
                raise FeishuError(TRANSIENT, "FEISHU_BAD_RESPONSE", "飞书返回非 JSON", retryable=True) from None

            code = int(body.get("code", 0))
            if code != 0:
                category = _OAUTH_ERROR_CODE_MAP.get(code, TRANSIENT)
                retryable = category in (RATE_LIMIT, TIMEOUT, TRANSIENT)
                result = f"feishu_{code}"
                raise FeishuError(category, f"FEISHU_{code}", str(body.get("msg", "未知错误")), retryable=retryable)
            # 返回完整响应体：有的接口（app_access_token）字段在顶层，其余在 data 内
            return body
        finally:
            log_external_call(
                dependency="feishu",
                method=method,
                path=path,
                duration_ms=(time.perf_counter() - start) * 1000,
                status=status_code,
                result=result,
            )


def _bundle_from_data(data: dict[str, Any]) -> FeishuTokenBundle:
    return FeishuTokenBundle(
        access_token=data.get("access_token", ""),
        token_type=data.get("token_type", "Bearer"),
        refresh_token=data.get("refresh_token"),
        access_expires_in=int(data.get("expires_in", 0)),
        refresh_expires_in=int(data.get("refresh_expires_in") or 0) if data.get("refresh_expires_in") else None,
        scope=data.get("scope"),
    )
