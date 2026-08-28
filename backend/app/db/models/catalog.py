"""目录/知识库配置表（knowledge schema，DD-03 §5.6 扩展）。"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from .mixins import RowVersionMixin, TimestampMixin


class Product(Base, TimestampMixin, RowVersionMixin):
    __tablename__ = "products"
    __table_args__ = (
        Index("uq_products_code", "code", unique=True),
        {"schema": "knowledge", "comment": "产品"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ENABLED", server_default="ENABLED"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class ProductVersion(Base, TimestampMixin, RowVersionMixin):
    __tablename__ = "product_versions"
    __table_args__ = (
        Index("uq_product_versions_product_code", "product_id", "version_code", unique=True),
        {"schema": "knowledge", "comment": "产品版本"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge.products.id"), nullable=False
    )
    version_code: Mapped[str] = mapped_column(String(128), nullable=False)
    big_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # legacy columns retained for database compatibility; no longer exposed by API
    major_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minor_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ENABLED", server_default="ENABLED"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class DocumentType(Base, TimestampMixin, RowVersionMixin):
    __tablename__ = "document_types"
    __table_args__ = (
        Index("uq_document_types_code", "code", unique=True),
        {"schema": "knowledge", "comment": "文档类型"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ENABLED", server_default="ENABLED"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class ProductForm(Base, TimestampMixin, RowVersionMixin):
    __tablename__ = "product_forms"
    __table_args__ = (
        Index("uq_product_forms_code", "code", unique=True),
        {"schema": "knowledge", "comment": "产品形态"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ENABLED", server_default="ENABLED"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class SourcePriority(Base, TimestampMixin, RowVersionMixin):
    __tablename__ = "source_priorities"
    __table_args__ = (
        Index("uq_source_priorities_source_code", "source_code", unique=True),
        Index("uq_source_priorities_priority", "priority", unique=True),
        {"schema": "knowledge", "comment": "来源优先级"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ENABLED", server_default="ENABLED"
    )
