import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from .mixins import TimestampMixin


class ExternalIdentity(Base, TimestampMixin):
    """auth.external_identities —— 外部身份绑定（DD-03 §4.3）。"""

    __tablename__ = "external_identities"
    __table_args__ = (
        Index(
            "uq_external_identity_provider_tenant_user",
            "provider",
            "tenant_key",
            "external_user_id",
            unique=True,
        ),
        Index("ix_external_identities_user", "user_id"),
        {"schema": "auth", "comment": "外部身份绑定"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # FEISHU
    tenant_key: Mapped[str] = mapped_column(String(128), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(128), nullable=False)  # 飞书稳定 user_id
    open_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    union_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    binding_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="BOUND", server_default="BOUND"
    )
    bound_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    unbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    profile_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ExternalCredential(Base):
    """auth.external_credentials —— 加密保存的外部访问凭据（DD-03 §4.4）。

    access/refresh token 只保存信封加密后的密文，明文永不落库、不进入日志与响应。
    """

    __tablename__ = "external_credentials"
    __table_args__ = {"schema": "auth", "comment": "外部访问凭据（密文）"}

    identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.external_identities.id"), primary_key=True
    )
    access_token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class LoginSession(Base):
    """auth.login_sessions —— 登录会话（DD-03 §4.5）。Cookie 只存随机令牌，库内只存哈希。"""

    __tablename__ = "login_sessions"
    __table_args__ = (
        Index("ix_login_sessions_user_expires", "user_id", "expires_at"),
        {"schema": "auth", "comment": "登录会话"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id"), nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthState(Base):
    """auth.oauth_states —— 飞书 OAuth state（防 CSRF，一次性、短有效期）。"""

    __tablename__ = "oauth_states"
    __table_args__ = (
        Index("uq_oauth_states_state", "state", unique=True),
        {"schema": "auth", "comment": "飞书 OAuth state"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    redirect_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
