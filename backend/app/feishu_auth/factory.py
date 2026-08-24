"""OAuth 客户端工厂：按配置选择 Fake 或 Real 飞书实现。"""

from __future__ import annotations

from ..core.config import Settings, get_settings
from .base import FeishuOAuthClient
from .fake import FakeFeishuOAuthClient
from .real import RealFeishuOAuthClient


def get_feishu_oauth_client(settings: Settings | None = None) -> FeishuOAuthClient:
    s = settings or get_settings()
    if s.feishu_provider == "real":
        if not s.feishu_app_id or not s.feishu_app_secret:
            raise RuntimeError(
                "FEISHU_PROVIDER=real 时必须配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET"
            )
        return RealFeishuOAuthClient(
            app_id=s.feishu_app_id,
            app_secret=s.feishu_app_secret,
            base_url=s.feishu_base_url,
            passport_host=s.feishu_passport_host,
            timeout_seconds=s.feishu_timeout_seconds,
        )
    return FakeFeishuOAuthClient()
