"""include waiting-for-approval answers in the conversation open guard"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_answer_open_per_conversation", table_name="answers", schema="conversation")
    op.create_index(
        "uq_answer_open_per_conversation", "answers", ["conversation_id"], unique=True,
        schema="conversation",
        postgresql_where=sa.text("status IN ('PENDING', 'WAITING', 'RETRIEVING', 'STREAMING')"),
    )


def downgrade() -> None:
    op.drop_index("uq_answer_open_per_conversation", table_name="answers", schema="conversation")
    op.create_index(
        "uq_answer_open_per_conversation", "answers", ["conversation_id"], unique=True,
        schema="conversation",
        postgresql_where=sa.text("status IN ('PENDING', 'RETRIEVING', 'STREAMING')"),
    )
