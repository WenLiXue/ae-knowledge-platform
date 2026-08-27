"""add pgvector extension and vector document table"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "b3c7f1a9e042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "vector_documents",
        sa.Column("doc_id", sa.String(256), primary_key=True),
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("generation", sa.String(128), nullable=False),
        sa.Column("title", sa.String(512)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.CHAR(64)),
        sa.Column("heading_path", sa.ARRAY(sa.Text())),
        sa.Column("locator", sa.JSON()),
        sa.Column("chunk_type", sa.String(32)),
        sa.Column("ordinal", sa.Integer()),
        sa.Column("metadata_snapshot", sa.JSON()),
        sa.Column("embedding", Vector()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        schema="knowledge",
    )
    op.create_index("ix_vector_documents_generation", "vector_documents", ["generation"], schema="knowledge")
    op.create_index("ix_vector_documents_version", "vector_documents", ["version_id"], schema="knowledge")


def downgrade() -> None:
    op.drop_index("ix_vector_documents_version", table_name="vector_documents", schema="knowledge")
    op.drop_index("ix_vector_documents_generation", table_name="vector_documents", schema="knowledge")
    op.drop_table("vector_documents", schema="knowledge")
