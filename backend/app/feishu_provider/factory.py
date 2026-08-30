"""Provider 工厂：按配置选择 Fake 或 Real 飞书实现。"""

from __future__ import annotations

from ..core.config import Settings, get_settings
from .base import FeishuDocumentProvider
from .fake import FakeFeishuProvider
from .feishu_document_provider import RealFeishuProvider


def get_feishu_provider(settings: Settings | None = None) -> FeishuDocumentProvider:
    s = settings or get_settings()
    if s.feishu_provider == "real":
        if not s.feishu_app_id or not s.feishu_app_secret:
            raise RuntimeError(
                "FEISHU_PROVIDER=real 时必须配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET"
            )
        return RealFeishuProvider(
            app_id=s.feishu_app_id,
            app_secret=s.feishu_app_secret,
            base_url=s.feishu_base_url,
            timeout_seconds=s.feishu_timeout_seconds,
        )
    return FakeFeishuProvider()
