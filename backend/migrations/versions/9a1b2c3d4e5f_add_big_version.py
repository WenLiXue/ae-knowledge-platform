"""add string big-version field for product catalog entries"""
from alembic import op
import sqlalchemy as sa

revision = "9a1b2c3d4e5f"
down_revision = "f8c9d0e1f2a3"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("product_versions", sa.Column("big_version", sa.String(128), nullable=True), schema="knowledge")

def downgrade() -> None:
    op.drop_column("product_versions", "big_version", schema="knowledge")
