"""persist safe answer progress and tool events"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "fc2f3a4b5c6d"
down_revision = "fb1e2f3a4c5d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("answers", sa.Column("progress_events", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")), schema="conversation")


def downgrade() -> None:
    op.drop_column("answers", "progress_events", schema="conversation")
