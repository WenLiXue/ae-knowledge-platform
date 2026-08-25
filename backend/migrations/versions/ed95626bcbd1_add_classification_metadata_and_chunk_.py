"""add classification metadata and chunk schema

新增分类/元数据/切片三张表（DD-19 §5.1-5.3）：
- knowledge.classification_results：分类运行结果，UNIQUE(version_id, input_hash)；
- knowledge.document_metadata：版本级文档元数据（version_id 主键）；
- knowledge.document_chunks：文档切片，UNIQUE(version_id, ordinal)。

Revision ID: ed95626bcbd1
Revises: eb6fca22ccd9
Create Date: 2026-08-25 14:43:44.352054

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ed95626bcbd1'
down_revision: Union[str, Sequence[str], None] = 'eb6fca22ccd9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'classification_results',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('version_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='RUNNING', nullable=False),
        sa.Column('relevance', sa.String(length=32), nullable=True),
        sa.Column('relevance_confidence', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('output_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('evidence_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('missing_fields', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('reason_summary', sa.Text(), nullable=True),
        sa.Column('model_key', sa.String(length=128), nullable=True),
        sa.Column('model_revision', sa.String(length=128), nullable=True),
        sa.Column('prompt_revision', sa.String(length=128), nullable=True),
        sa.Column('input_builder_revision', sa.String(length=128), nullable=True),
        sa.Column('classification_config_revision', sa.BigInteger(), nullable=True),
        sa.Column('input_hash', sa.CHAR(length=64), nullable=True),
        sa.Column('token_usage_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_code', sa.String(length=128), nullable=True),
        sa.Column('error_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['version_id'], ['knowledge.document_versions.id'], name=op.f('fk_classification_results_version_id_document_versions')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_classification_results')),
        schema='knowledge',
        comment='分类结果',
    )
    op.create_index('uq_classification_results_version_hash', 'classification_results', ['version_id', 'input_hash'], unique=True, schema='knowledge')
    op.create_index('ix_classification_results_version_status', 'classification_results', ['version_id', 'status'], unique=False, schema='knowledge')
    op.create_index('ix_classification_results_relevance_created', 'classification_results', ['relevance', 'created_at'], unique=False, schema='knowledge')

    op.create_table(
        'document_metadata',
        sa.Column('version_id', sa.UUID(), nullable=False),
        sa.Column('classification_result_id', sa.UUID(), nullable=True),
        sa.Column('product_id', sa.UUID(), nullable=True),
        sa.Column('product_version_id', sa.UUID(), nullable=True),
        sa.Column('document_type_id', sa.UUID(), nullable=True),
        sa.Column('product_form_id', sa.UUID(), nullable=True),
        sa.Column('is_domestic', sa.Boolean(), nullable=True),
        sa.Column('module_name', sa.Text(), nullable=True),
        sa.Column('business_topic', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('keywords', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('field_sources', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('field_confidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('updated_by_user_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['classification_result_id'], ['knowledge.classification_results.id'], name=op.f('fk_document_metadata_classification_result_id_classification_results')),
        sa.ForeignKeyConstraint(['document_type_id'], ['knowledge.document_types.id'], name=op.f('fk_document_metadata_document_type_id_document_types')),
        sa.ForeignKeyConstraint(['product_form_id'], ['knowledge.product_forms.id'], name=op.f('fk_document_metadata_product_form_id_product_forms')),
        sa.ForeignKeyConstraint(['product_id'], ['knowledge.products.id'], name=op.f('fk_document_metadata_product_id_products')),
        sa.ForeignKeyConstraint(['product_version_id'], ['knowledge.product_versions.id'], name=op.f('fk_document_metadata_product_version_id_product_versions')),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['auth.users.id'], name=op.f('fk_document_metadata_updated_by_user_id_users')),
        sa.ForeignKeyConstraint(['version_id'], ['knowledge.document_versions.id'], name=op.f('fk_document_metadata_version_id_document_versions')),
        sa.PrimaryKeyConstraint('version_id', name=op.f('pk_document_metadata')),
        schema='knowledge',
        comment='文档元数据',
    )
    op.create_index('ix_document_metadata_product', 'document_metadata', ['product_id'], unique=False, schema='knowledge')
    op.create_index('ix_document_metadata_doc_type', 'document_metadata', ['document_type_id'], unique=False, schema='knowledge')

    op.create_table(
        'document_chunks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('version_id', sa.UUID(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('chunk_type', sa.String(length=32), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_sha256', sa.CHAR(length=64), nullable=False),
        sa.Column('heading_path', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('locator_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('metadata_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('token_count', sa.Integer(), nullable=True),
        sa.Column('embedding_status', sa.String(length=32), server_default='PENDING', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['version_id'], ['knowledge.document_versions.id'], name=op.f('fk_document_chunks_version_id_document_versions')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_document_chunks')),
        schema='knowledge',
        comment='文档切片',
    )
    op.create_index('uq_document_chunks_version_ordinal', 'document_chunks', ['version_id', 'ordinal'], unique=True, schema='knowledge')
    op.create_index('ix_document_chunks_version', 'document_chunks', ['version_id'], unique=False, schema='knowledge')
    op.create_index('ix_document_chunks_content_sha', 'document_chunks', ['content_sha256'], unique=False, schema='knowledge')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_document_chunks_version_ordinal', table_name='document_chunks', schema='knowledge')
    op.drop_index('ix_document_chunks_version', table_name='document_chunks', schema='knowledge')
    op.drop_index('ix_document_chunks_content_sha', table_name='document_chunks', schema='knowledge')
    op.drop_table('document_chunks', schema='knowledge')

    op.drop_index('ix_document_metadata_product', table_name='document_metadata', schema='knowledge')
    op.drop_index('ix_document_metadata_doc_type', table_name='document_metadata', schema='knowledge')
    op.drop_table('document_metadata', schema='knowledge')

    op.drop_index('uq_classification_results_version_hash', table_name='classification_results', schema='knowledge')
    op.drop_index('ix_classification_results_version_status', table_name='classification_results', schema='knowledge')
    op.drop_index('ix_classification_results_relevance_created', table_name='classification_results', schema='knowledge')
    op.drop_table('classification_results', schema='knowledge')
