"""飞书 OAuth 客户端抽象。

实现飞书扫码登录/网页授权码流程（端点契约经官方示例 demo 验证）：
- build_authorize_url：构造 passport 扫码授权 URL；
- exchange_code：用授权码换取 user_access_token/refresh_token；
- get_user_info：用 user_access_token 获取用户身份（open_id/union_id/user_id/tenant_key）；
- refresh_access_token：刷新过期凭据。

Fake 与 Real 都实现本接口；业务层只依赖接口，不直接触碰飞书凭据。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class FeishuTokenBundle:
    access_token: str
    token_type: str            # 通常 "Bearer"
    refresh_token: str | None
    access_expires_in: int     # 秒
    refresh_expires_in: int | None = None
    scope: str | None = None


@dataclass
class FeishuUserProfile:
    open_id: str
    tenant_key: str
    union_id: str | None = None
    user_id: str | None = None     # 稳定 user_id（需 contact:user.id scope，否则回退 open_id）
    name: str | None = None
    avatar_url: str | None = None


class FeishuOAuthClient(ABC):
    @abstractmethod
    def build_authorize_url(self, state: str, redirect_uri: str) -> str:
        """构造飞书扫码授权 URL。"""

    @abstractmethod
    def exchange_code(self, code: str) -> FeishuTokenBundle:
        """用授权码换取 token 包。"""

    @abstractmethod
    def get_user_info(self, access_token: str, token_type: str) -> FeishuUserProfile:
        """用 user_access_token 获取用户身份。"""

    @abstractmethod
    def refresh_access_token(self, refresh_token: str) -> FeishuTokenBundle:
        """用 refresh_token 刷新凭据。"""
