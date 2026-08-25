"""audit logs

Revision ID: 5e4fbd53f203
Revises: 3a040f953e87
Create Date: 2026-08-25 10:21:44.130425

操作审计日志（DD-17 §5）：
- platform.audit_logs：只追加的审计事件表；
- platform.audit_exports：异步导出任务状态表。

审计记录只追加，业务应用数据库角色仅授予 SELECT/INSERT；
record_hash 为规范序列化后的 HMAC-SHA256，prev_hash 构成哈希链用于事后发现篡改。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5e4fbd53f203'
down_revision: Union[str, Sequence[str], None] = '3a040f953e87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('audit_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_type', sa.String(length=16), nullable=False),
    sa.Column('actor_user_id', sa.UUID(), nullable=True),
    sa.Column('actor_key', sa.String(length=128), nullable=True),
    sa.Column('actor_name', sa.String(length=128), nullable=False),
    sa.Column('actor_account', sa.String(length=320), nullable=True),
    sa.Column('module', sa.String(length=32), nullable=False),
    sa.Column('action', sa.String(length=128), nullable=False),
    sa.Column('target_type', sa.String(length=64), nullable=True),
    sa.Column('target_id', sa.String(length=128), nullable=True),
    sa.Column('target_name', sa.String(length=256), nullable=True),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('summary', sa.String(length=512), nullable=False),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('trace_id', sa.String(length=64), nullable=True),
    sa.Column('causation_id', sa.UUID(), nullable=True),
    sa.Column('source_type', sa.String(length=16), nullable=False),
    sa.Column('source_ip', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.String(length=256), nullable=True),
    sa.Column('prev_hash', sa.CHAR(length=64), nullable=True),
    sa.Column('record_hash', sa.CHAR(length=64), nullable=False),
    sa.Column('schema_version', sa.SmallInteger(), server_default=sa.text('1'), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['auth.users.id'], name=op.f('fk_audit_logs_actor_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs')),
    schema='platform',
    comment='操作审计日志'
    )
    op.create_index('ix_audit_logs_occurred_id', 'audit_logs', [sa.text('occurred_at DESC'), sa.text('id DESC')], unique=False, schema='platform')
    op.create_index('ix_audit_logs_actor_occurred', 'audit_logs', ['actor_user_id', sa.text('occurred_at DESC')], unique=False, schema='platform')
    op.create_index('ix_audit_logs_module_outcome_occurred', 'audit_logs', ['module', 'outcome', sa.text('occurred_at DESC')], unique=False, schema='platform')
    op.create_index('ix_audit_logs_action_occurred', 'audit_logs', ['action', sa.text('occurred_at DESC')], unique=False, schema='platform')
    op.create_index('ix_audit_logs_target_occurred', 'audit_logs', ['target_type', 'target_id', sa.text('occurred_at DESC')], unique=False, schema='platform')
    op.create_index('ix_audit_logs_request_id', 'audit_logs', ['request_id'], unique=False, schema='platform')

    op.create_table('audit_exports',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('requested_by_user_id', sa.UUID(), nullable=True),
    sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='PENDING', nullable=False),
    sa.Column('filters', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('row_count', sa.Integer(), nullable=True),
    sa.Column('file_path', sa.String(length=512), nullable=True),
    sa.Column('file_sha256', sa.CHAR(length=64), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['requested_by_user_id'], ['auth.users.id'], name=op.f('fk_audit_exports_requested_by_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_exports')),
    schema='platform',
    comment='审计导出任务'
    )
    op.create_index('ix_audit_exports_requested_at', 'audit_exports', ['requested_at'], unique=False, schema='platform')


def downgrade() -> None:
    """Downgrade schema. 生产不应执行：会删除审计历史。"""
    op.drop_index('ix_audit_exports_requested_at', table_name='audit_exports', schema='platform')
    op.drop_table('audit_exports', schema='platform')
    op.drop_index('ix_audit_logs_request_id', table_name='audit_logs', schema='platform')
    op.drop_index('ix_audit_logs_target_occurred', table_name='audit_logs', schema='platform')
    op.drop_index('ix_audit_logs_action_occurred', table_name='audit_logs', schema='platform')
    op.drop_index('ix_audit_logs_module_outcome_occurred', table_name='audit_logs', schema='platform')
    op.drop_index('ix_audit_logs_actor_occurred', table_name='audit_logs', schema='platform')
    op.drop_index('ix_audit_logs_occurred_id', table_name='audit_logs', schema='platform')
    op.drop_table('audit_logs', schema='platform')
