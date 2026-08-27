"""add Agent tool and skill management tables"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS agent")
    op.create_table(
        "agent_tool_configs",
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("source", sa.String(32), server_default="BUILTIN", nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_agent_tool_configs")),
        schema="agent",
    )
    op.create_table(
        "agent_skills",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(1024), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.String(32), server_default="1.0.0", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("source", sa.String(32), server_default="IMPORTED", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_skills")),
        sa.UniqueConstraint("name", name="uq_agent_skills_name"),
        schema="agent",
    )
    op.create_index("ix_agent_skills_enabled", "agent_skills", ["enabled"], schema="agent")
    op.create_table(
        "agent_mcp_servers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("endpoint", sa.String(2048), nullable=False),
        sa.Column("transport", sa.String(16), server_default="STREAMABLE_HTTP", nullable=False),
        sa.Column("description", sa.String(1024), server_default="", nullable=False),
        sa.Column("auth_type", sa.String(32), server_default="NONE", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(32), server_default="NOT_TESTED", nullable=False),
        sa.Column("last_error", sa.String(512), nullable=True),
        sa.Column("discovered_tools", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_mcp_servers")),
        sa.UniqueConstraint("name", name="uq_agent_mcp_servers_name"),
        schema="agent",
    )
    op.create_index("ix_agent_mcp_servers_enabled", "agent_mcp_servers", ["enabled"], schema="agent")
    tools = [
        ("identity.current_user", "1.0", "查询当前登录用户的真实身份、显示名称、角色和状态。"),
        ("knowledge.search", "1.0", "在当前用户可见的企业知识库中检索产品、版本和配置资料。"),
        ("task.retry", "1.0", "重新排队一个失败的后台处理任务。"),
        ("skill.load", "1.0", "按需加载一个已启用技能的详细说明。"),
    ]
    for name, version, description in tools:
        op.get_bind().execute(
            sa.text("INSERT INTO agent.agent_tool_configs (name, version, description) VALUES (:name, :version, :description)"),
            {"name": name, "version": version, "description": description},
        )


def downgrade() -> None:
    op.drop_index("ix_agent_mcp_servers_enabled", table_name="agent_mcp_servers", schema="agent")
    op.drop_table("agent_mcp_servers", schema="agent")
    op.drop_index("ix_agent_skills_enabled", table_name="agent_skills", schema="agent")
    op.drop_table("agent_skills", schema="agent")
    op.drop_table("agent_tool_configs", schema="agent")
    op.execute("DROP SCHEMA IF EXISTS agent")
