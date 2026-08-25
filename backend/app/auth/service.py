"""认证应用服务：飞书 OAuth 起止、回调绑定、解绑。

身份匹配规则对齐 DD-08 §4.3：以 (provider, tenant_key, external_user_id) 查询；
外部 user_id 优先取飞书稳定 user_id，未提供时回退 open_id。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models.auth import ExternalCredential, ExternalIdentity, OAuthState
from ..db.models.user import User
from ..feishu_auth.base import FeishuOAuthClient
from ..feishu_provider.base import FeishuError
from . import crypto

PROVIDER_FEISHU = "FEISHU"
KEY_VERSION = "1"


class FeishuAuthError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class OAuthLoginResult:
    """OAuth 回调处理结果：user + 本次请求是否发生绑定（新建/重新绑定）。"""

    user: User
    newly_bound: bool


def start_oauth(
    session: Session,
    oauth_client: FeishuOAuthClient,
    redirect_uri: str,
    state_ttl_minutes: int = 10,
) -> dict[str, str]:
    state = secrets.token_urlsafe(24)
    session.add(
        OAuthState(
            state=state,
            redirect_uri=redirect_uri,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=state_ttl_minutes),
        )
    )
    session.commit()
    return {"authorize_url": oauth_client.build_authorize_url(state, redirect_uri), "state": state}


def process_oauth_callback(
    session: Session,
    oauth_client: FeishuOAuthClient,
    code: str,
    state: str,
    key_b64: str,
) -> User:
    now = datetime.now(timezone.utc)

    state_row = session.execute(
        select(OAuthState).where(OAuthState.state == state)
    ).scalars().first()
    if state_row is None or state_row.used_at is not None or state_row.expires_at < now:
        raise FeishuAuthError("INVALID_OAUTH_STATE", "OAuth state 无效或已过期", status=400)
    state_row.used_at = now

    try:
        bundle = oauth_client.exchange_code(code)
        profile = oauth_client.get_user_info(bundle.access_token, bundle.token_type)
    except FeishuError as exc:
        raise FeishuAuthError(exc.code, exc.message, status=401) from exc

    external_user_id = profile.user_id or profile.open_id
    if not external_user_id or not profile.tenant_key:
        raise FeishuAuthError("FEISHU_IDENTITY_MISSING", "飞书未返回用户身份", status=400)

    identity = session.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == PROVIDER_FEISHU,
            ExternalIdentity.tenant_key == profile.tenant_key,
            ExternalIdentity.external_user_id == external_user_id,
        )
    ).scalars().first()

    if identity is not None:
        newly_bound = identity.binding_status == "UNBOUND"
        if identity.binding_status == "UNBOUND":
            identity.binding_status = "BOUND"
            identity.unbound_at = None
        user = session.get(User, identity.user_id)
        if user is None:
            raise FeishuAuthError("FEISHU_USER_MISSING", "绑定的系统用户不存在", status=409)
    else:
        newly_bound = True
        user = User(
            display_name=profile.name or external_user_id,
            status="ACTIVE",
            is_admin=False,
            created_source="FEISHU",
        )
        session.add(user)
        session.flush()
        identity = ExternalIdentity(
            user_id=user.id,
            provider=PROVIDER_FEISHU,
            tenant_key=profile.tenant_key,
            external_user_id=external_user_id,
            open_id=profile.open_id,
            union_id=profile.union_id,
            binding_status="BOUND",
            bound_at=now,
            profile_snapshot={"name": profile.name, "avatar_url": profile.avatar_url},
        )
        session.add(identity)
        session.flush()

    _store_credentials(session, identity, bundle, key_b64, now)
    # 只 flush 不 commit：登录会话与审计记录由 API 层在同一事务内追加后统一提交
    session.flush()
    return OAuthLoginResult(user=user, newly_bound=newly_bound)


def _store_credentials(
    session: Session,
    identity: ExternalIdentity,
    bundle,
    key_b64: str,
    now: datetime,
) -> None:
    cred = session.get(ExternalCredential, identity.id)
    if cred is None:
        cred = ExternalCredential(identity_id=identity.id)
        session.add(cred)
    cred.access_token_ciphertext = crypto.encrypt(bundle.access_token, key_b64)
    cred.refresh_token_ciphertext = (
        crypto.encrypt(bundle.refresh_token, key_b64) if bundle.refresh_token else None
    )
    cred.access_expires_at = now + timedelta(seconds=bundle.access_expires_in)
    cred.refresh_expires_at = (
        now + timedelta(seconds=bundle.refresh_expires_in)
        if bundle.refresh_expires_in
        else None
    )
    cred.scope = bundle.scope
    cred.key_version = KEY_VERSION


def unbind_feishu(session: Session, user_id) -> None:
    identity = session.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.user_id == user_id,
            ExternalIdentity.provider == PROVIDER_FEISHU,
            ExternalIdentity.binding_status == "BOUND",
        )
    ).scalars().first()
    if identity is None:
        raise FeishuAuthError("FEISHU_NOT_BOUND", "该用户未绑定飞书", status=409)
    identity.binding_status = "UNBOUND"
    identity.unbound_at = datetime.now(timezone.utc)
    cred = session.get(ExternalCredential, identity.id)
    if cred is not None:
        cred.access_token_ciphertext = b""
        cred.refresh_token_ciphertext = None
