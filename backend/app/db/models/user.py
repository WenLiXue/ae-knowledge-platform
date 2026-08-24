import uuid

from sqlalchemy import Boolean, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from .mixins import RowVersionMixin, TimestampMixin


class User(Base, TimestampMixin, RowVersionMixin):
    """auth.users —— 系统用户（DD-03 §4.1）。"""

    __tablename__ = "users"
    __table_args__ = {"schema": "auth", "comment": "系统用户"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ADMIN", server_default="ADMIN"
    )


Index(
    "uq_users_username_lower",
    func.lower(User.username),
    unique=True,
    postgresql_where=User.username.is_not(None),
)
