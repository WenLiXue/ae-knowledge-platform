"""add approval records for side-effecting agent tools"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WAITING 表示等待用户确认，不能允许同一会话继续创建并发回答。
    op.drop_index("uq_answer_open_per_conversation", table_name="answers", schema="conversation")
    op.create_index(
        "uq_answer_open_per_conversation",
        "answers",
        ["conversation_id"],
        unique=True,
        schema="conversation",
        postgresql_where=sa.text("status IN ('PENDING', 'WAITING', 'RETRIEVING', 'STREAMING')"),
    )
    op.create_table(
        "agent_approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("step_id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("decision_by", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="PENDING", nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("arguments_hash", sa.String(length=64), nullable=False),
        sa.Column("impact_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["conversation.agent_runs.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["conversation.agent_plans.id"]),
        sa.ForeignKeyConstraint(["step_id"], ["conversation.agent_plan_steps.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["decision_by"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="conversation",
        comment="Agent 工具确认",
    )
    op.create_index("ix_agent_approvals_run_status", "agent_approvals", ["run_id", "status"], schema="conversation")
    op.create_index("ix_agent_approvals_expires", "agent_approvals", ["expires_at"], schema="conversation")


def downgrade() -> None:
    op.drop_index("ix_agent_approvals_expires", table_name="agent_approvals", schema="conversation")
    op.drop_index("ix_agent_approvals_run_status", table_name="agent_approvals", schema="conversation")
    op.drop_table("agent_approvals", schema="conversation")
    op.drop_index("uq_answer_open_per_conversation", table_name="answers", schema="conversation")
    op.create_index(
        "uq_answer_open_per_conversation",
        "answers",
        ["conversation_id"],
        unique=True,
        schema="conversation",
        postgresql_where=sa.text("status IN ('PENDING', 'RETRIEVING', 'STREAMING')"),
    )
