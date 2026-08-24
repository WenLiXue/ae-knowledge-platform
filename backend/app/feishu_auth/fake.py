"""FakeFeishuOAuthClient：确定性 mock，供开发与测试验证 OAuth 流程。

可配置返回的身份与 token；按 code 注入授权失败，按开关模拟 refresh 失败，
从而覆盖绑定、未授权、刷新等场景，无需真实飞书凭据。
"""

from __future__ import annotations

from ..feishu_provider.base import AUTH, FeishuError
from .base import FeishuOAuthClient, FeishuTokenBundle, FeishuUserProfile


class FakeFeishuOAuthClient(FeishuOAuthClient):
    def __init__(
        self,
        *,
        app_id: str = "fake-app",
        profile: FeishuUserProfile | None = None,
        access_token: str = "fake-access-token",
        refresh_token: str = "fake-refresh-token",
    ):
        self._app_id = app_id
        self._profile = profile or FeishuUserProfile(
            open_id="ou_fake_user", tenant_key="tenant_fake", user_id="u_fake_user", name="Fake 用户"
        )
        self._access_token = access_token
        self._refresh_token = refresh_token
        # 测试注入点
        self.exchange_fail_code: str | None = None   # 命中该 code 时 exchange_code 抛 AUTH
        self.refresh_should_fail: bool = False
        self.refresh_calls: int = 0

    def build_authorize_url(self, state: str, redirect_uri: str) -> str:
        return (
            f"https://passport.feishu.cn/suite/passport/oauth/authorize"
            f"?client_id={self._app_id}&redirect_uri={redirect_uri}&response_type=code&state={state}"
        )

    def exchange_code(self, code: str) -> FeishuTokenBundle:
        if self.exchange_fail_code and code == self.exchange_fail_code:
            raise FeishuError(AUTH, "FEISHU_AUTH_EXPIRED", "模拟授权失败", retryable=False)
        return FeishuTokenBundle(
            access_token=self._access_token,
            token_type="Bearer",
            refresh_token=self._refresh_token,
            access_expires_in=7200,
            refresh_expires_in=2592000,
            scope="docx:document:readonly wiki:wiki:readonly",
        )

    def get_user_info(self, access_token: str, token_type: str) -> FeishuUserProfile:
        return self._profile

    def refresh_access_token(self, refresh_token: str) -> FeishuTokenBundle:
        self.refresh_calls += 1
        if self.refresh_should_fail:
            raise FeishuError(AUTH, "FEISHU_REFRESH_INVALID", "refresh token 已失效", retryable=False)
        return FeishuTokenBundle(
            access_token="fake-access-token-2",
            token_type="Bearer",
            refresh_token="fake-refresh-token-2",
            access_expires_in=7200,
            refresh_expires_in=2592000,
        )
