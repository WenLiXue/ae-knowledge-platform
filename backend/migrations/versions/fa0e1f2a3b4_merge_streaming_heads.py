"""merge the existing version catalog and streaming answer migration heads"""

from alembic import op

revision = "fa0e1f2a3b4"
down_revision = ("f9d0e1f2a3b4", "9a1b2c3d4e5f")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
