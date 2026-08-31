"""add resumable answer draft text for streaming output"""

from alembic import op
import sqlalchemy as sa

revision = "f9d0e1f2a3b4"
down_revision = "f8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("answers", sa.Column("draft_text", sa.Text(), nullable=True), schema="conversation")


def downgrade() -> None:
    op.drop_column("answers", "draft_text", schema="conversation")
