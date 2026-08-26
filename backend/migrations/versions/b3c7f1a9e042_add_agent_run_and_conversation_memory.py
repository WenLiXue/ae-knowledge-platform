"""add agent_runs and conversation_memories tables

DD-21 §13：LangGraph 知识助手 Agent 的会话记忆与运行记录。
- conversation.conversation_memories：会话滚动记忆（摘要/实体/约束/待解决主题，
  revision 乐观锁；原始消息永不因摘要而删除）；
- conversation.agent_runs：每次 answer 对应一条 Agent 运行记录
  （answer_id 唯一；checkpoint_thread_id=answer_id）。

Revision ID: b3c7f1a9e042
Revises: 7f4da183aa20
Create Date: 2026-08-26 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b3c7f1a9e042'
down_revision: Union[str, Sequence[str], None] = '7f4da183aa20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'conversation_memories',
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('summary', sa.Text(), server_default='', nullable=False),
        sa.Column('entities', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('constraints', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('unresolved_topics', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('last_message_id', sa.UUID(), nullable=True),
        sa.Column('token_estimate', sa.Integer(), server_default='0', nullable=False),
        sa.Column('revision', sa.Integer(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.conversations.id'], name=op.f('fk_conversation_memories_conversation_id_conversations')),
        sa.ForeignKeyConstraint(['last_message_id'], ['conversation.messages.id'], name=op.f('fk_conversation_memories_last_message_id_messages')),
        sa.PrimaryKeyConstraint('conversation_id', name=op.f('pk_conversation_memories')),
        schema='conversation',
        comment='会话滚动记忆',
    )

    op.create_table(
        'agent_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('answer_id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='PENDING', nullable=False),
        sa.Column('graph_version', sa.String(length=64), nullable=False),
        sa.Column('operation', sa.String(length=32), nullable=True),
        sa.Column('current_node', sa.String(length=64), nullable=True),
        sa.Column('step_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_steps', sa.Integer(), server_default='12', nullable=False),
        sa.Column('checkpoint_thread_id', sa.String(length=128), nullable=False),
        sa.Column('degradation_flags', postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column('timings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('token_usage', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_code', sa.String(length=128), nullable=True),
        sa.Column('error_summary', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['answer_id'], ['conversation.answers.id'], name=op.f('fk_agent_runs_answer_id_answers')),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.conversations.id'], name=op.f('fk_agent_runs_conversation_id_conversations')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_runs')),
        schema='conversation',
        comment='Agent 运行记录',
    )
    op.create_index('uq_agent_runs_answer', 'agent_runs', ['answer_id'], unique=True, schema='conversation')
    op.create_index('ix_agent_runs_conversation', 'agent_runs', ['conversation_id'], unique=False, schema='conversation')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_agent_runs_conversation', table_name='agent_runs', schema='conversation')
    op.drop_index('uq_agent_runs_answer', table_name='agent_runs', schema='conversation')
    op.drop_table('agent_runs', schema='conversation')
    op.drop_table('conversation_memories', schema='conversation')
