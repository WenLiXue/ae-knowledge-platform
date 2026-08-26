"""add conversation message answer citation feedback tables

DD-19 §5.4 / DD-08 §10-14 / DD-10：会话与问答持久化。
- conversation.conversations：会话（ACTIVE/ARCHIVED/DELETED，条件快照）；
- conversation.messages：用户/助手消息（不物理覆盖历史）；
- conversation.answers：回答（PENDING→RETRIEVING→STREAMING→SUCCEEDED，
  以及 FAILED/CANCELED；progress_stage 细阶段；同会话最多一个未终结 Answer）；
- conversation.answer_citations：引用快照（不依赖未来当前版本）；
- conversation.answer_feedback：(answer_id, user_id) 唯一、幂等更新。

Revision ID: 7f4da183aa20
Revises: 335e73de80f5
Create Date: 2026-08-25 17:11:40.895120

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7f4da183aa20'
down_revision: Union[str, Sequence[str], None] = '335e73de80f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OPEN_STATUSES = ("PENDING", "RETRIEVING", "STREAMING")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'conversations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=512), server_default='新会话', nullable=False),
        sa.Column('status', sa.String(length=32), server_default='ACTIVE', nullable=False),
        sa.Column('filters_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['auth.users.id'], name=op.f('fk_conversations_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations')),
        schema='conversation',
        comment='会话',
    )
    op.create_index('ix_conversations_user_updated', 'conversations', ['user_id', 'updated_at'], unique=False, schema='conversation')

    op.create_table(
        'messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.conversations.id'], name=op.f('fk_messages_conversation_id_conversations')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_messages')),
        schema='conversation',
        comment='消息',
    )
    op.create_index('ix_messages_conversation_created', 'messages', ['conversation_id', 'created_at'], unique=False, schema='conversation')

    op.create_table(
        'answers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('message_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='PENDING', nullable=False),
        sa.Column('progress_stage', sa.String(length=32), nullable=True),
        sa.Column('answer_type', sa.String(length=32), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('blocks_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('degradation_flags', postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column('retrieval_config_revision', sa.BigInteger(), nullable=True),
        sa.Column('retrieval_run_id', sa.UUID(), nullable=True),
        sa.Column('model_key', sa.String(length=128), nullable=True),
        sa.Column('index_generation', sa.String(length=128), nullable=True),
        sa.Column('cancel_requested', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('error_code', sa.String(length=128), nullable=True),
        sa.Column('error_summary', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.conversations.id'], name=op.f('fk_answers_conversation_id_conversations')),
        sa.ForeignKeyConstraint(['message_id'], ['conversation.messages.id'], name=op.f('fk_answers_message_id_messages')),
        sa.ForeignKeyConstraint(['retrieval_run_id'], ['conversation.retrieval_runs.id'], name=op.f('fk_answers_retrieval_run_id_retrieval_runs')),
        sa.ForeignKeyConstraint(['user_id'], ['auth.users.id'], name=op.f('fk_answers_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_answers')),
        schema='conversation',
        comment='回答',
    )
    op.create_index('ix_answers_conversation_created', 'answers', ['conversation_id', 'created_at'], unique=False, schema='conversation')
    op.create_index('uq_answer_open_per_conversation', 'answers', ['conversation_id'], unique=True, schema='conversation', postgresql_where=sa.text("status IN ('PENDING', 'RETRIEVING', 'STREAMING')"))

    op.create_table(
        'answer_citations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('answer_id', sa.UUID(), nullable=False),
        sa.Column('citation_no', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.UUID(), nullable=True),
        sa.Column('version_id', sa.UUID(), nullable=True),
        sa.Column('chunk_id', sa.UUID(), nullable=True),
        sa.Column('document_title', sa.String(length=512), nullable=False),
        sa.Column('document_type_code', sa.String(length=128), nullable=True),
        sa.Column('version_label', sa.String(length=128), nullable=True),
        sa.Column('heading_path', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('locator_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('excerpt', sa.Text(), nullable=True),
        sa.Column('original_url', sa.Text(), nullable=True),
        sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['answer_id'], ['conversation.answers.id'], name=op.f('fk_answer_citations_answer_id_answers')),
        sa.ForeignKeyConstraint(['source_id'], ['knowledge.knowledge_sources.id'], name=op.f('fk_answer_citations_source_id_knowledge_sources')),
        sa.ForeignKeyConstraint(['version_id'], ['knowledge.document_versions.id'], name=op.f('fk_answer_citations_version_id_document_versions')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_answer_citations')),
        schema='conversation',
        comment='回答引用快照',
    )
    op.create_index('ix_answer_citations_answer_no', 'answer_citations', ['answer_id', 'citation_no'], unique=False, schema='conversation')

    op.create_table(
        'answer_feedback',
        sa.Column('answer_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('rating', sa.String(length=16), nullable=False),
        sa.Column('reason_codes', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['answer_id'], ['conversation.answers.id'], name=op.f('fk_answer_feedback_answer_id_answers')),
        sa.ForeignKeyConstraint(['user_id'], ['auth.users.id'], name=op.f('fk_answer_feedback_user_id_users')),
        sa.PrimaryKeyConstraint('answer_id', 'user_id', name=op.f('pk_answer_feedback')),
        schema='conversation',
        comment='回答反馈',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('answer_feedback', schema='conversation')
    op.drop_index('ix_answer_citations_answer_no', table_name='answer_citations', schema='conversation')
    op.drop_table('answer_citations', schema='conversation')
    op.drop_index('uq_answer_open_per_conversation', table_name='answers', schema='conversation')
    op.drop_index('ix_answers_conversation_created', table_name='answers', schema='conversation')
    op.drop_table('answers', schema='conversation')
    op.drop_index('ix_messages_conversation_created', table_name='messages', schema='conversation')
    op.drop_table('messages', schema='conversation')
    op.drop_index('ix_conversations_user_updated', table_name='conversations', schema='conversation')
    op.drop_table('conversations', schema='conversation')
