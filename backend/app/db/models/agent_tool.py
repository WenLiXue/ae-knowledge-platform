"""Persisted configuration for code-owned Agent tools."""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from .mixins import TimestampMixin


class AgentToolConfig(Base, TimestampMixin):
    __tablename__ = "agent_tool_configs"
    __table_args__ = ({"schema": "agent", "comment": "Agent 工具启停配置"},)

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="BUILTIN", server_default="BUILTIN")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
