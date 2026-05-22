from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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


class ShopIdentity(TimestampMixin, Base):
    __tablename__ = "shop_identities"
    __table_args__: Any = (
        CheckConstraint(
            "status IN ('active', 'hold', 'disabled', 'out_of_scope')",
            name="ck_shop_identities_status_known",
        ),
        Index("ix_shop_identities_status", "status"),
        Index("ix_shop_identities_preferred_source", "preferred_source"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(Text)
    preferred_source: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    notes: Mapped[str | None] = mapped_column(Text)
    locked_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    source_shops: Mapped[list["Shop"]] = relationship(back_populates="shop_identity")


class Shop(TimestampMixin, Base):
    __tablename__ = "shops"
    __table_args__: Any = (
        UniqueConstraint("source", "source_id", name="uq_shops_source_source_id"),
        CheckConstraint(
            "source_type IN ('2gis', 'official_api', 'official_html')",
            name="ck_shops_source_type_known",
        ),
        Index("ix_shops_shop_identity_id", "shop_identity_id"),
        Index("ix_shops_source_type", "source_type"),
        Index("ix_shops_next_scrape_at", "next_scrape_at"),
        Index("ix_shops_scrape_status", "scrape_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    shop_identity_id: Mapped[int | None] = mapped_column(ForeignKey("shop_identities.id"))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_scrape_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scrape_interval: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("86400")
    )
    scrape_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'new'"))
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    shop_identity: Mapped[ShopIdentity | None] = relationship(back_populates="source_shops")
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
    canonical_products: Mapped[list["CanonicalProduct"]] = relationship(back_populates="category")
    category_overrides: Mapped[list["CategoryOverride"]] = relationship(
        back_populates="category",
        foreign_keys="CategoryOverride.category_id",
    )


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
    is_not_product: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    shop: Mapped[Shop] = relationship(back_populates="source_products")
    category: Mapped[Category | None] = relationship(back_populates="source_products")
    price_snapshots: Mapped[list["PriceSnapshot"]] = relationship(back_populates="source_product")
    product_matches: Mapped[list["ProductMatch"]] = relationship(back_populates="source_product")
    category_overrides: Mapped[list["CategoryOverride"]] = relationship(
        back_populates="source_product",
        foreign_keys="CategoryOverride.source_product_id",
    )


class CategoryOverride(TimestampMixin, Base):
    __tablename__ = "category_overrides"
    __table_args__: Any = (
        Index("ix_category_overrides_category_id", "category_id"),
        Index("ix_category_overrides_status", "status"),
        Index("ix_category_overrides_created_at", "created_at"),
        Index(
            "uq_category_overrides_source_product_active",
            "source_product_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_product_id: Mapped[int] = mapped_column(
        ForeignKey("source_products.id"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    previous_category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
    deactivated_by: Mapped[str | None] = mapped_column(Text)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source_product: Mapped[SourceProduct] = relationship(
        back_populates="category_overrides",
        foreign_keys=[source_product_id],
    )
    category: Mapped[Category] = relationship(
        back_populates="category_overrides",
        foreign_keys=[category_id],
    )
    previous_category: Mapped[Category | None] = relationship(
        foreign_keys=[previous_category_id],
    )


class CanonicalProduct(TimestampMixin, Base):
    __tablename__ = "canonical_products"
    __table_args__: Any = (
        Index("ix_canonical_products_category_id", "category_id"),
        Index("ix_canonical_products_normalized_title", "normalized_title"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_title: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    unit_raw: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    match_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )

    category: Mapped[Category | None] = relationship(back_populates="canonical_products")
    product_matches: Mapped[list["ProductMatch"]] = relationship(back_populates="canonical_product")


class ProductMatch(Base):
    __tablename__ = "product_matches"
    __table_args__: Any = (
        Index("ix_product_matches_canonical_product_id", "canonical_product_id"),
        Index("ix_product_matches_source_product_id", "source_product_id"),
        Index("ix_product_matches_status_confidence", "status", "confidence"),
        Index(
            "uq_product_matches_source_product_accepted",
            "source_product_id",
            unique=True,
            postgresql_where=text("status = 'accepted'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    canonical_product_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_products.id"), nullable=False
    )
    source_product_id: Mapped[int] = mapped_column(
        ForeignKey("source_products.id"), nullable=False
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    canonical_product: Mapped[CanonicalProduct] = relationship(
        back_populates="product_matches"
    )
    source_product: Mapped[SourceProduct] = relationship(back_populates="product_matches")


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
