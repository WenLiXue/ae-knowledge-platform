"""平台配置与密钥表（platform schema，DD-03 §8）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, LargeBinary, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class ConfigRevision(Base):
    """platform.config_revisions —— 配置版本（DD-03 §8.1）。"""

    __tablename__ = "config_revisions"
    __table_args__ = (
        Index(
            "uq_active_config_namespace",
            "namespace",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        {"schema": "platform", "comment": "配置版本"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="DRAFT", server_default="DRAFT"
    )
    created_by_user_id: Mapped[object | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SecretValue(Base):
    """platform.secret_values —— 配置密钥密文（不进入 config_revisions.content）。"""

    __tablename__ = "secret_values"
    __table_args__ = (
        Index("uq_secret_values_ns_key", "namespace", "key_name", unique=True),
        {"schema": "platform", "comment": "配置密钥密文"},
    )

    namespace: Mapped[str] = mapped_column(String(128), primary_key=True)
    key_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
