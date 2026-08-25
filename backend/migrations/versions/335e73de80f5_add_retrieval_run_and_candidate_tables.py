"""add retrieval run and candidate tables

DD-19 §5.4：新增 conversation schema 与检索运行/候选两张表：
- conversation.retrieval_runs：一次检索运行的记录（模式、降级 flag、配置 revision、
  阶段耗时、候选数量、证据状态）；
- conversation.retrieval_candidates：Top-K 候选明细（各阶段 rank/分数、是否进入
  最终证据及排除原因），(retrieval_run_id, chunk_id) 唯一。

Revision ID: 335e73de80f5
Revises: ed95626bcbd1
Create Date: 2026-08-25 16:36:59.893000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '335e73de80f5'
down_revision: Union[str, Sequence[str], None] = 'ed95626bcbd1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS conversation")

    op.create_table(
        'retrieval_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('operation', sa.String(length=32), nullable=False),
        sa.Column('normalized_question', sa.Text(), nullable=False),
        sa.Column('query_texts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('product_id', sa.UUID(), nullable=True),
        sa.Column('version_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('document_type_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('mode', sa.String(length=32), nullable=False),
        sa.Column('degradation_flags', postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='SUCCEEDED', nullable=False),
        sa.Column('error_code', sa.String(length=128), nullable=True),
        sa.Column('config_revision', sa.BigInteger(), nullable=True),
        sa.Column('embedding_model_key', sa.String(length=128), nullable=True),
        sa.Column('rerank_model_key', sa.String(length=128), nullable=True),
        sa.Column('params_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('stage_duration_ms', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('candidate_counts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('evidence_status', sa.String(length=32), nullable=True),
        sa.Column('evidence_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['knowledge.products.id'], name=op.f('fk_retrieval_runs_product_id_products')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_retrieval_runs')),
        schema='conversation',
        comment='检索运行记录',
    )
    op.create_index('ix_retrieval_runs_created', 'retrieval_runs', ['created_at'], unique=False, schema='conversation')

    op.create_table(
        'retrieval_candidates',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('retrieval_run_id', sa.UUID(), nullable=False),
        sa.Column('chunk_id', sa.UUID(), nullable=False),
        sa.Column('source_id', sa.UUID(), nullable=True),
        sa.Column('version_id', sa.UUID(), nullable=True),
        sa.Column('ordinal', sa.Integer(), nullable=True),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('bm25_rank', sa.Integer(), nullable=True),
        sa.Column('vector_rank', sa.Integer(), nullable=True),
        sa.Column('bm25_score', sa.Float(), nullable=True),
        sa.Column('vector_score', sa.Float(), nullable=True),
        sa.Column('rrf_score', sa.Float(), nullable=True),
        sa.Column('rerank_score', sa.Float(), nullable=True),
        sa.Column('final_score', sa.Float(), nullable=True),
        sa.Column('is_evidence', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('evidence_rank', sa.Integer(), nullable=True),
        sa.Column('exclusion_reason', sa.String(length=256), nullable=True),
        sa.Column('score_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('title_snapshot', sa.String(length=512), nullable=True),
        sa.Column('content_sha256', sa.CHAR(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['chunk_id'], ['knowledge.document_chunks.id'], name=op.f('fk_retrieval_candidates_chunk_id_document_chunks')),
        sa.ForeignKeyConstraint(['retrieval_run_id'], ['conversation.retrieval_runs.id'], name=op.f('fk_retrieval_candidates_retrieval_run_id_retrieval_runs')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_retrieval_candidates')),
        schema='conversation',
        comment='检索候选',
    )
    op.create_index('uq_retrieval_candidates_run_chunk', 'retrieval_candidates', ['retrieval_run_id', 'chunk_id'], unique=True, schema='conversation')
    op.create_index('ix_retrieval_candidates_run', 'retrieval_candidates', ['retrieval_run_id'], unique=False, schema='conversation')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_retrieval_candidates_run', table_name='retrieval_candidates', schema='conversation')
    op.drop_index('uq_retrieval_candidates_run_chunk', table_name='retrieval_candidates', schema='conversation')
    op.drop_table('retrieval_candidates', schema='conversation')

    op.drop_index('ix_retrieval_runs_created', table_name='retrieval_runs', schema='conversation')
    op.drop_table('retrieval_runs', schema='conversation')

    # 本迁移是 conversation schema 的创建者；后续迁移若在其中新增表，reverse 顺序会先
    # 由那些迁移自行 drop，因此这里空 schema 后安全删除。非空时 DROP 会显式失败，防数据丢失。
    op.execute("DROP SCHEMA IF EXISTS conversation")
