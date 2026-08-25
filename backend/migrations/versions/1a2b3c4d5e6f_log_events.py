"""log_events

Revision ID: 1a2b3c4d5e6f
Revises: 5e4fbd53f203
Create Date: 2026-08-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, Sequence[str], None] = '5e4fbd53f203'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'log_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('service', sa.String(length=16), server_default='api', nullable=False),
        sa.Column('level', sa.String(length=16), nullable=False),
        sa.Column('logger', sa.String(length=128), nullable=True),
        sa.Column('message', sa.String(length=1024), nullable=False),
        sa.Column('error_code', sa.String(length=128), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('task_id', sa.String(length=36), nullable=True),
        sa.Column('source_id', sa.String(length=36), nullable=True),
        sa.Column('version_id', sa.String(length=36), nullable=True),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('traceback', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ['user_id'], ['auth.users.id'],
            name=op.f('fk_log_events_user_id_users'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_log_events')),
        schema='platform',
        comment='运行日志（ERROR 级持久化）',
    )
    op.create_index('ix_log_events_created', 'log_events', ['created_at'], unique=False, schema='platform')
    op.create_index('ix_log_events_service_created', 'log_events', ['service', 'created_at'], unique=False, schema='platform')
    op.create_index('ix_log_events_level_created', 'log_events', ['level', 'created_at'], unique=False, schema='platform')
    op.create_index('ix_log_events_request_id', 'log_events', ['request_id'], unique=False, schema='platform')
    op.create_index('ix_log_events_task_id', 'log_events', ['task_id'], unique=False, schema='platform')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_log_events_task_id', table_name='log_events', schema='platform')
    op.drop_index('ix_log_events_request_id', table_name='log_events', schema='platform')
    op.drop_index('ix_log_events_level_created', table_name='log_events', schema='platform')
    op.drop_index('ix_log_events_service_created', table_name='log_events', schema='platform')
    op.drop_index('ix_log_events_created', table_name='log_events', schema='platform')
    op.drop_table('log_events', schema='platform')
