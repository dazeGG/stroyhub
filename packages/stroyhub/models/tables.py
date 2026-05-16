from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stroyhub.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Shop(TimestampMixin, Base):
    __tablename__ = "shops"
    __table_args__: Any = (
        UniqueConstraint("source", "source_id", name="uq_shops_source_source_id"),
        Index("ix_shops_next_scrape_at", "next_scrape_at"),
        Index("ix_shops_scrape_status", "scrape_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_scrape_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scrape_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'new'"))
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    source_products: Mapped[list["SourceProduct"]] = relationship(back_populates="shop")
    scrape_runs: Mapped[list["ScrapeRun"]] = relationship(back_populates="shop")


class Category(TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__: Any = (
        UniqueConstraint(
            "parent_id",
            "slug",
            name="uq_categories_parent_id_slug",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_categories_parent_id", "parent_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    parent: Mapped["Category | None"] = relationship(
        back_populates="children", remote_side="Category.id"
    )
    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    source_products: Mapped[list["SourceProduct"]] = relationship(back_populates="category")


class SourceProduct(TimestampMixin, Base):
    __tablename__ = "source_products"
    __table_args__: Any = (
        Index(
            "uq_source_products_source_shop_source_product_id",
            "source",
            "shop_id",
            "source_product_id",
            unique=True,
            postgresql_where=text("source_product_id IS NOT NULL"),
        ),
        Index(
            "uq_source_products_source_shop_fingerprint",
            "source",
            "shop_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("fingerprint IS NOT NULL"),
        ),
        Index("ix_source_products_shop_id", "shop_id"),
        Index("ix_source_products_category_id", "category_id"),
        Index("ix_source_products_normalized_title", "normalized_title"),
        Index("ix_source_products_last_seen_at", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_product_id: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    category_raw: Mapped[str | None] = mapped_column(Text)
    unit_raw: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    shop: Mapped[Shop] = relationship(back_populates="source_products")
    category: Mapped[Category | None] = relationship(back_populates="source_products")
    price_snapshots: Mapped[list["PriceSnapshot"]] = relationship(back_populates="source_product")


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    __table_args__: Any = (
        Index("ix_price_snapshots_source_product_id_parsed_at", "source_product_id", "parsed_at"),
        Index("ix_price_snapshots_parsed_at", "parsed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_product_id: Mapped[int] = mapped_column(ForeignKey("source_products.id"), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'RUB'"))
    unit_raw: Mapped[str | None] = mapped_column(Text)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parsed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    source_product: Mapped[SourceProduct] = relationship(back_populates="price_snapshots")


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    __table_args__: Any = (
        Index("ix_scrape_runs_shop_id_started_at", "shop_id", "started_at"),
        Index("ix_scrape_runs_source_started_at", "source", "started_at"),
        Index("ix_scrape_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    shop_id: Mapped[int | None] = mapped_column(ForeignKey("shops.id"))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items_seen: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    items_saved: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    shop: Mapped[Shop | None] = relationship(back_populates="scrape_runs")
