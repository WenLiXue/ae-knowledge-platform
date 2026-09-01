"""Persisted MCP server connections and discovered tool metadata."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from .mixins import TimestampMixin


class AgentMcpServer(Base, TimestampMixin):
    __tablename__ = "agent_mcp_servers"
    __table_args__ = (UniqueConstraint("name", name="uq_agent_mcp_servers_name"), Index("ix_agent_mcp_servers_enabled", "enabled"), {"schema": "agent", "comment": "Agent MCP Server 管理配置"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(2048), nullable=False)
    transport: Mapped[str] = mapped_column(String(16), nullable=False, default="STREAMABLE_HTTP", server_default="STREAMABLE_HTTP")
    description: Mapped[str] = mapped_column(String(1024), nullable=False, default="", server_default="")
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False, default="NONE", server_default="NONE")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_TESTED", server_default="NOT_TESTED")
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    discovered_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
