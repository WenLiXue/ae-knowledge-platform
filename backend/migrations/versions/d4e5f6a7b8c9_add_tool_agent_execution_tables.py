"""add durable tool-agent plans and tool call records"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="DRAFT", nullable=False),
        sa.Column("completion_criteria", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["conversation.agent_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="conversation",
        comment="Agent 执行计划",
    )
    op.create_index("ix_agent_plans_run", "agent_plans", ["run_id"], schema="conversation")
    op.create_index("uq_agent_plans_run_revision", "agent_plans", ["run_id", "revision"], unique=True, schema="conversation")

    op.create_table(
        "agent_plan_steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("capability", sa.String(length=128), nullable=False),
        sa.Column("dependencies", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("risk", sa.String(length=24), server_default="READ_ONLY", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="PENDING", nullable=False),
        sa.Column("input_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["conversation.agent_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="conversation",
        comment="Agent 计划步骤",
    )
    op.create_index("uq_agent_plan_steps_plan_key", "agent_plan_steps", ["plan_id", "step_key"], unique=True, schema="conversation")
    op.create_index("ix_agent_plan_steps_plan_status", "agent_plan_steps", ["plan_id", "status"], schema="conversation")

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("step_id", sa.UUID(), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("tool_version", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=True),
        sa.Column("arguments_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("external_operation_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["conversation.agent_runs.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["conversation.agent_plans.id"]),
        sa.ForeignKeyConstraint(["step_id"], ["conversation.agent_plan_steps.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="conversation",
        comment="Agent 工具调用",
    )
    op.create_index("ix_agent_tool_calls_run_created", "agent_tool_calls", ["run_id", "created_at"], schema="conversation")
    op.create_index("uq_agent_tool_calls_step_attempt", "agent_tool_calls", ["step_id", "attempt"], unique=True, schema="conversation")


def downgrade() -> None:
    op.drop_index("uq_agent_tool_calls_step_attempt", table_name="agent_tool_calls", schema="conversation")
    op.drop_index("ix_agent_tool_calls_run_created", table_name="agent_tool_calls", schema="conversation")
    op.drop_table("agent_tool_calls", schema="conversation")
    op.drop_index("ix_agent_plan_steps_plan_status", table_name="agent_plan_steps", schema="conversation")
    op.drop_index("uq_agent_plan_steps_plan_key", table_name="agent_plan_steps", schema="conversation")
    op.drop_table("agent_plan_steps", schema="conversation")
    op.drop_index("uq_agent_plans_run_revision", table_name="agent_plans", schema="conversation")
    op.drop_index("ix_agent_plans_run", table_name="agent_plans", schema="conversation")
    op.drop_table("agent_plans", schema="conversation")
