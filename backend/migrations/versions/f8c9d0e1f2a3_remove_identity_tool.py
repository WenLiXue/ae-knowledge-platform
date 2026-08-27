"""move authenticated identity from tool registry to runtime context"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "f7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM agent.agent_tool_configs WHERE name = :name"
    ).bindparams(name="identity.current_user"))


def downgrade() -> None:
    op.execute(sa.text(
        """INSERT INTO agent.agent_tool_configs (name, version, description)
           VALUES (:name, :version, :description)
           ON CONFLICT (name) DO NOTHING"""
    ).bindparams(
        name="identity.current_user",
        version="1.0",
        description="已废弃：当前登录身份由 Agent 运行时上下文提供。",
    ))
