"""add safe user-facing progress message to answers"""

from alembic import op
import sqlalchemy as sa

revision = "fb1e2f3a4c5d"
down_revision = "fa0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "answers",
        sa.Column("progress_message", sa.String(length=256), nullable=True),
        schema="conversation",
    )


def downgrade() -> None:
    op.drop_column("answers", "progress_message", schema="conversation")
