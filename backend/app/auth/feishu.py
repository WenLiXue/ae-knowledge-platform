"""用户飞书身份与凭据解析。

`get_user_access_token` 供 API 与 Worker 使用：读取绑定身份 → 解密凭据 →
过期时用 refresh_token 刷新并重加密存储 → 返回明文 user_access_token。
明文 token 不落库、不进日志、不进响应。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..db.models.auth import ExternalCredential, ExternalIdentity
from ..feishu_auth.base import FeishuOAuthClient
from ..feishu_provider.base import FeishuError
from . import crypto

PROVIDER_FEISHU = "FEISHU"


def get_feishu_identity(session: Session, user_id) -> ExternalIdentity | None:
    return session.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.user_id == user_id,
            ExternalIdentity.provider == PROVIDER_FEISHU,
            ExternalIdentity.binding_status == "BOUND",
        )
    ).scalars().first()


def has_feishu_binding(session: Session, user_id) -> bool:
    return get_feishu_identity(session, user_id) is not None


def get_user_access_token(
    session: Session,
    user_id,
    oauth_client: FeishuOAuthClient,
    key_b64: str | None = None,
) -> str | None:
    """返回用户可用的 user_access_token；未绑定/不可续期/刷新失败时返回 None。"""
    key = key_b64 or get_settings().token_enc_key
    identity = get_feishu_identity(session, user_id)
    if identity is None:
        return None
    cred = session.get(ExternalCredential, identity.id)
    if cred is None or not cred.access_token_ciphertext:
        return None

    access = crypto.decrypt(cred.access_token_ciphertext, key)
    now = datetime.now(timezone.utc)
    if cred.access_expires_at and cred.access_expires_at > now + timedelta(seconds=60):
        return access

    # access token 将过期 → 尝试刷新
    if not cred.refresh_token_ciphertext:
        return None
    refresh = crypto.decrypt(cred.refresh_token_ciphertext, key)
    try:
        bundle = oauth_client.refresh_access_token(refresh)
    except FeishuError:
        # 刷新失败（refresh token 失效/授权被撤销）→ 视为无可用凭据
        return None

    cred.access_token_ciphertext = crypto.encrypt(bundle.access_token, key)
    if bundle.refresh_token:
        cred.refresh_token_ciphertext = crypto.encrypt(bundle.refresh_token, key)
    cred.access_expires_at = now + timedelta(seconds=bundle.access_expires_in)
    if bundle.refresh_expires_in:
        cred.refresh_expires_at = now + timedelta(seconds=bundle.refresh_expires_in)
    session.flush()
    return bundle.access_token
