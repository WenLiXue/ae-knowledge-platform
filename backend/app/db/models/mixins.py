from datetime import datetime

from sqlalchemy import DateTime, Integer, func, text
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RowVersionMixin:
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
