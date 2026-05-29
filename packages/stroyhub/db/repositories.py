from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stroyhub.models.tables import (
    CanonicalProduct,
    Category,
    CategoryOverride,
    OperatorDecision,
    PriceSnapshot,
    ProductMatch,
    ScrapeRun,
    Shop,
    ShopIdentity,
    SourceCategoryMapping,
    SourceProduct,
)
from stroyhub.parsers.common import normalize_title

JsonObject = dict[str, Any]
PRODUCT_MATCH_STATUSES = frozenset({"accepted", "candidate", "rejected", "superseded"})
CATEGORY_OVERRIDE_STATUSES = frozenset({"active", "replaced", "reverted"})
SOURCE_CATEGORY_MAPPING_STATUSES = frozenset({"active", "non_product", "disabled"})
SHOP_IDENTITY_STATUSES = frozenset({"active", "hold", "disabled", "out_of_scope"})
SHOP_SOURCE_TYPES = frozenset({"2gis", "official_api", "official_html"})
OPERATOR_DECISION_TYPES = frozenset({"categorization", "normalization", "data_quality"})
_DEFAULT_SOURCE_TYPES = {
    "2gis": "2gis",
    "unicom": "official_api",
    "metalltorg": "official_html",
}


@dataclass(frozen=True, kw_only=True)
class ShopUpsert:
    source: str
    source_id: str
    name: str
    shop_identity_id: int | None = None
    source_type: str | None = None
    address: str | None = None
    url: str | None = None
    raw: JsonObject | None = None
    last_scraped_at: datetime | None = None
    next_scrape_at: datetime | None = None
    scrape_interval: int | None = None
    scrape_status: str | None = None
    error_count: int | None = None


@dataclass(frozen=True, kw_only=True)
class ShopIdentityCreate:
    display_name: str
    address: str | None = None
    website_url: str | None = None
    preferred_source: str | None = None
    status: str = "active"
    notes: str | None = None
    locked_fields: JsonObject | None = None


@dataclass(frozen=True, kw_only=True)
class ShopIdentityUpdate:
    display_name: str | None = None
    address: str | None = None
    website_url: str | None = None
    preferred_source: str | None = None
    status: str | None = None
    notes: str | None = None
    locked_fields: JsonObject | None = None


@dataclass(frozen=True, kw_only=True)
class CategoryUpsert:
    slug: str
    name: str
    parent_id: int | None = None


@dataclass(frozen=True, kw_only=True)
class CategoryOverrideCreate:
    source_product_id: int
    category_id: int
    reason: str | None = None
    actor: str | None = None


@dataclass(frozen=True, kw_only=True)
class CategoryOverrideRevert:
    source_product_id: int
    actor: str | None = None


@dataclass(frozen=True, kw_only=True)
class SourceCategoryMappingUpsert:
    source: str
    raw_category: str
    category_id: int | None = None
    status: str = "active"
    confidence: Decimal = Decimal("1.000")
    reason: str | None = None
    actor: str | None = None


@dataclass(frozen=True, kw_only=True)
class SourceProductUpsert:
    shop_id: int
    source: str
    title: str
    normalized_title: str
    source_product_id: str | None = None
    fingerprint: str | None = None
    description: str | None = None
    category_id: int | None = None
    category_raw: str | None = None
    unit_raw: str | None = None
    image_url: str | None = None
    source_updated_at: datetime | None = None
    raw: JsonObject | None = None
    observed_at: datetime | None = None
    is_active: bool = True
    is_not_product: bool | None = None


@dataclass(frozen=True, kw_only=True)
class PriceSnapshotCreate:
    source_product_id: int
    price: Decimal | None
    price_kind: str = "exact"
    currency: str = "RUB"
    unit_raw: str | None = None
    source_updated_at: datetime | None = None
    parsed_at: datetime | None = None
    raw: JsonObject | None = None


@dataclass(frozen=True, kw_only=True)
class ScrapeRunCreate:
    source: str
    shop_id: int | None = None
    status: str = "running"
    started_at: datetime | None = None
    raw: JsonObject | None = None


@dataclass(frozen=True, kw_only=True)
class CanonicalProductCreate:
    title: str
    normalized_title: str
    category_id: int | None = None
    brand: str | None = None
    model: str | None = None
    unit_raw: str | None = None
    attributes: JsonObject | None = None
    match_status: str = "active"


@dataclass(frozen=True, kw_only=True)
class ProductMatchCreate:
    canonical_product_id: int
    source_product_id: int
    confidence: Decimal
    method: str
    status: str = "candidate"
    matched_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    reason: JsonObject | None = None


@dataclass(frozen=True, kw_only=True)
class OperatorDecisionCreate:
    decision_type: str
    action: str
    entity_type: str
    entity_id: int | None = None
    source_product_id: int | None = None
    canonical_product_id: int | None = None
    product_match_id: int | None = None
    category_id: int | None = None
    actor: str | None = None
    reason: str | None = None
    previous_state: JsonObject | None = None
    new_state: JsonObject | None = None
    evidence: JsonObject | None = None
    alternatives: JsonObject | None = None
    metadata: JsonObject | None = None
    decided_at: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class OperatorDecisionFilters:
    decision_type: str | None = None
    action: str | None = None
    actor: str | None = None
    source_product_id: int | None = None
    canonical_product_id: int | None = None
    product_match_id: int | None = None
    category_id: int | None = None
    limit: int | None = None
    offset: int = 0


class ShopRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_source_id(self, *, source: str, source_id: str) -> Shop | None:
        statement = select(Shop).where(Shop.source == source, Shop.source_id == source_id)
        return self._session.scalar(statement)

    def upsert(self, data: ShopUpsert) -> Shop:
        shop = self.get_by_source_id(source=data.source, source_id=data.source_id)
        source_type = _validated_source_type(data.source_type, source=data.source)

        if shop is None:
            shop = Shop(
                source=data.source,
                source_id=data.source_id,
                source_type=source_type,
                name=data.name,
            )
            self._session.add(shop)

        if data.shop_identity_id is not None:
            if self._session.get(ShopIdentity, data.shop_identity_id) is None:
                raise ValueError("shop identity not found")
            shop.shop_identity_id = data.shop_identity_id

        shop.source_type = source_type
        shop.name = data.name
        if data.address is not None or shop.id is None:
            shop.address = data.address
        if data.url is not None or shop.id is None:
            shop.url = data.url
        if data.raw is not None or shop.id is None:
            shop.raw = data.raw
        if data.last_scraped_at is not None:
            shop.last_scraped_at = data.last_scraped_at
        if data.next_scrape_at is not None:
            shop.next_scrape_at = data.next_scrape_at

        if data.scrape_interval is not None:
            shop.scrape_interval = data.scrape_interval
        if data.scrape_status is not None:
            shop.scrape_status = data.scrape_status
        if data.error_count is not None:
            shop.error_count = data.error_count

        self._session.flush()
        return shop

    def list_due_for_scraping(
        self,
        *,
        now: datetime,
        source: str | None = None,
        source_type: str | None = None,
        limit: int | None = None,
    ) -> list[Shop]:
        statement = select(Shop).where(
            Shop.scrape_status.not_in(["disabled", "running"]),
            (Shop.next_scrape_at.is_(None) | (Shop.next_scrape_at <= now)),
        )
        if source is not None:
            statement = statement.where(Shop.source == source)
        if source_type is not None:
            statement = statement.where(Shop.source_type == source_type)
        statement = statement.order_by(Shop.next_scrape_at.asc().nullsfirst(), Shop.id.asc())
        if limit is not None:
            statement = statement.limit(limit)

        return list(self._session.scalars(statement))


class ShopIdentityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, identity_id: int) -> ShopIdentity | None:
        return self._session.get(ShopIdentity, identity_id)

    def create(self, data: ShopIdentityCreate) -> ShopIdentity:
        display_name = data.display_name.strip()
        if not display_name:
            raise ValueError("display_name must not be empty")
        _validate_shop_identity_status(data.status)
        preferred_source = _normalize_preferred_source(data.preferred_source)

        identity = ShopIdentity(
            display_name=display_name,
            address=data.address,
            website_url=data.website_url,
            preferred_source=preferred_source,
            status=data.status,
            notes=data.notes,
            locked_fields=data.locked_fields,
        )
        self._session.add(identity)
        self._session.flush()
        return identity

    def update(self, identity_id: int, data: ShopIdentityUpdate) -> ShopIdentity:
        identity = self.get(identity_id)
        if identity is None:
            raise ValueError("shop identity not found")

        locked_fields = set(identity.locked_fields or {})

        if data.display_name is not None and "display_name" not in locked_fields:
            display_name = data.display_name.strip()
            if not display_name:
                raise ValueError("display_name must not be empty")
            identity.display_name = display_name
        if data.address is not None and "address" not in locked_fields:
            identity.address = data.address
        if data.website_url is not None and "website_url" not in locked_fields:
            identity.website_url = data.website_url
        if data.preferred_source is not None:
            identity.preferred_source = _normalize_preferred_source(data.preferred_source)
        if data.status is not None:
            _validate_shop_identity_status(data.status)
            identity.status = data.status
        if data.notes is not None:
            identity.notes = data.notes
        if data.locked_fields is not None:
            identity.locked_fields = data.locked_fields

        self._session.flush()
        return identity

    def delete(self, identity_id: int) -> ShopIdentity:
        identity = self.get(identity_id)
        if identity is None:
            raise ValueError("shop identity not found")

        linked_shops = self._session.scalars(
            select(Shop).where(Shop.shop_identity_id == identity.id)
        )
        for shop in linked_shops:
            shop.shop_identity_id = None

        self._session.delete(identity)
        self._session.flush()
        return identity

    def link_shop(self, *, identity_id: int, shop_id: int) -> Shop:
        identity = self.get(identity_id)
        if identity is None:
            raise ValueError("shop identity not found")

        shop = self._session.get(Shop, shop_id)
        if shop is None:
            raise ValueError("shop not found")

        shop.shop_identity_id = identity.id
        self._session.flush()
        return shop

    def unlink_shop(self, *, shop_id: int) -> Shop:
        shop = self._session.get(Shop, shop_id)
        if shop is None:
            raise ValueError("shop not found")

        shop.shop_identity_id = None
        self._session.flush()
        return shop

    def list_source_shops(self, identity_id: int) -> list[Shop]:
        statement = (
            select(Shop)
            .where(Shop.shop_identity_id == identity_id)
            .order_by(Shop.source_type.asc(), Shop.name.asc(), Shop.id.asc())
        )
        return list(self._session.scalars(statement))


class CategoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_slug(self, *, slug: str, parent_id: int | None = None) -> Category | None:
        statement = select(Category).where(Category.slug == slug)
        if parent_id is None:
            statement = statement.where(Category.parent_id.is_(None))
        else:
            statement = statement.where(Category.parent_id == parent_id)

        return self._session.scalar(statement)

    def get(self, category_id: int) -> Category | None:
        return self._session.get(Category, category_id)

    def has_children(self, category_id: int) -> bool:
        statement = select(Category.id).where(Category.parent_id == category_id).limit(1)
        return self._session.scalar(statement) is not None

    def upsert(self, data: CategoryUpsert) -> Category:
        category = self.get_by_slug(slug=data.slug, parent_id=data.parent_id)
        if category is None:
            category = Category(slug=data.slug, name=data.name, parent_id=data.parent_id)
            self._session.add(category)

        category.name = data.name
        self._session.flush()
        return category


class SourceCategoryMappingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_source_raw(
        self,
        *,
        source: str,
        raw_category: str,
    ) -> SourceCategoryMapping | None:
        normalized_source = _normalized_required_text(source, field="source").lower()
        normalized_raw_category = normalize_title(
            _normalized_required_text(raw_category, field="raw_category")
        )
        statement = select(SourceCategoryMapping).where(
            SourceCategoryMapping.source == normalized_source,
            SourceCategoryMapping.normalized_raw_category == normalized_raw_category,
        )
        return self._session.scalar(statement)

    def list_all(self, *, source: str | None = None) -> list[SourceCategoryMapping]:
        statement = select(SourceCategoryMapping).order_by(
            SourceCategoryMapping.source.asc(),
            SourceCategoryMapping.normalized_raw_category.asc(),
            SourceCategoryMapping.id.asc(),
        )
        if source is not None:
            normalized_source = source.strip().lower()
            if normalized_source:
                statement = statement.where(SourceCategoryMapping.source == normalized_source)
        return list(self._session.scalars(statement))

    def upsert(self, data: SourceCategoryMappingUpsert) -> SourceCategoryMapping:
        status = data.status.strip().lower()
        if status not in SOURCE_CATEGORY_MAPPING_STATUSES:
            raise ValueError("source category mapping status is invalid")

        source = _normalized_required_text(data.source, field="source").lower()
        raw_category = _normalized_required_text(data.raw_category, field="raw_category")
        normalized_raw_category = normalize_title(raw_category)
        if not normalized_raw_category:
            raise ValueError("raw_category must not be empty")

        category_id = data.category_id if status == "active" else None
        if status == "active":
            if category_id is None:
                raise ValueError("active source category mapping requires category_id")
            if self._session.get(Category, category_id) is None:
                raise ValueError("category not found")

        if not (Decimal("0.000") <= data.confidence <= Decimal("1.000")):
            raise ValueError("source category mapping confidence is invalid")

        mapping = self.get_by_source_raw(source=source, raw_category=raw_category)
        actor = _normalized_optional_text(data.actor)
        if mapping is None:
            mapping = SourceCategoryMapping(
                source=source,
                raw_category=raw_category,
                normalized_raw_category=normalized_raw_category,
                created_by=actor,
            )
            self._session.add(mapping)

        mapping.raw_category = raw_category
        mapping.normalized_raw_category = normalized_raw_category
        mapping.category_id = category_id
        mapping.status = status
        mapping.confidence = data.confidence.quantize(Decimal("0.001"))
        mapping.reason = _normalized_optional_text(data.reason)
        mapping.updated_by = actor

        self._session.flush()
        return mapping


class CategoryOverrideRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_active(self, source_product_id: int) -> CategoryOverride | None:
        statement = select(CategoryOverride).where(
            CategoryOverride.source_product_id == source_product_id,
            CategoryOverride.status == "active",
        )
        return self._session.scalar(statement)

    def list_for_product(self, source_product_id: int) -> list[CategoryOverride]:
        statement = (
            select(CategoryOverride)
            .where(CategoryOverride.source_product_id == source_product_id)
            .order_by(CategoryOverride.created_at.desc(), CategoryOverride.id.desc())
        )
        return list(self._session.scalars(statement))

    def create_or_replace(self, data: CategoryOverrideCreate) -> CategoryOverride:
        product = self._session.get(SourceProduct, data.source_product_id)
        if product is None:
            raise ValueError("source product not found")

        if self._session.get(Category, data.category_id) is None:
            raise ValueError("category not found")

        now = datetime.now(UTC)
        active_override = self.get_active(data.source_product_id)
        normalized_reason = _normalized_optional_text(data.reason)
        normalized_actor = _normalized_optional_text(data.actor)
        previous_category_id = product.category_id
        if active_override is not None:
            if (
                active_override.category_id == data.category_id
                and _normalized_optional_text(active_override.reason) == normalized_reason
                and _normalized_optional_text(active_override.created_by) == normalized_actor
            ):
                if product.category_id != data.category_id:
                    product.category_id = data.category_id
                    self._session.flush()
                return active_override
            previous_category_id = active_override.previous_category_id
            active_override.status = "replaced"
            active_override.updated_by = normalized_actor
            active_override.deactivated_by = normalized_actor
            active_override.deactivated_at = now

        override = CategoryOverride(
            source_product_id=data.source_product_id,
            category_id=data.category_id,
            previous_category_id=previous_category_id,
            reason=normalized_reason,
            status="active",
            created_by=normalized_actor,
            updated_by=normalized_actor,
        )
        self._session.add(override)
        product.category_id = data.category_id
        self._session.flush()
        return override

    def revert_active(self, data: CategoryOverrideRevert) -> CategoryOverride | None:
        active_override = self.get_active(data.source_product_id)
        if active_override is None:
            return None

        now = datetime.now(UTC)
        active_override.status = "reverted"
        active_override.updated_by = data.actor
        active_override.deactivated_by = data.actor
        active_override.deactivated_at = now

        product = self._session.get(SourceProduct, data.source_product_id)
        if product is not None:
            product.category_id = active_override.previous_category_id

        self._session.flush()
        return active_override


class SourceProductRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_upsert(self, data: SourceProductUpsert) -> SourceProduct | None:
        if data.source_product_id is None and data.fingerprint is None:
            raise ValueError("source products require source_product_id or fingerprint for upsert")

        if data.source_product_id is not None:
            statement = select(SourceProduct).where(
                SourceProduct.source == data.source,
                SourceProduct.shop_id == data.shop_id,
                SourceProduct.source_product_id == data.source_product_id,
            )
            product = self._session.scalar(statement)
            if product is not None:
                return product

        if data.fingerprint is not None:
            statement = select(SourceProduct).where(
                SourceProduct.source == data.source,
                SourceProduct.shop_id == data.shop_id,
                SourceProduct.fingerprint == data.fingerprint,
            )
            return self._session.scalar(statement)

        return None

    def upsert(self, data: SourceProductUpsert) -> SourceProduct:
        product = self.get_for_upsert(data)
        observed_at = data.observed_at

        if product is None:
            product = SourceProduct(
                shop_id=data.shop_id,
                source=data.source,
                title=data.title,
                normalized_title=data.normalized_title,
            )
            if observed_at is not None:
                product.first_seen_at = observed_at
            self._session.add(product)

        product.source_product_id = data.source_product_id
        product.fingerprint = data.fingerprint
        product.title = data.title
        product.normalized_title = data.normalized_title
        active_override = None
        if product.id is not None:
            active_override = CategoryOverrideRepository(self._session).get_active(product.id)

        product.description = data.description
        product.category_id = (
            active_override.category_id if active_override is not None else data.category_id
        )
        product.category_raw = data.category_raw
        product.unit_raw = data.unit_raw
        product.image_url = data.image_url
        product.source_updated_at = data.source_updated_at
        product.raw = data.raw
        product.is_active = data.is_active
        if data.is_not_product is not None:
            product.is_not_product = data.is_not_product

        if observed_at is not None:
            product.last_seen_at = observed_at

        self._session.flush()
        return product


def _normalized_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalized_required_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


class PriceSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, data: PriceSnapshotCreate) -> PriceSnapshot:
        price_kind = (
            "unknown" if data.price is None and data.price_kind == "exact" else data.price_kind
        )
        snapshot = PriceSnapshot(
            source_product_id=data.source_product_id,
            price=data.price,
            price_kind=price_kind,
            currency=data.currency,
            unit_raw=data.unit_raw,
            source_updated_at=data.source_updated_at,
            raw=data.raw,
        )

        if data.parsed_at is not None:
            snapshot.parsed_at = data.parsed_at

        self._session.add(snapshot)
        self._session.flush()
        return snapshot


class ScrapeRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def start(self, data: ScrapeRunCreate) -> ScrapeRun:
        scrape_run = ScrapeRun(
            source=data.source,
            shop_id=data.shop_id,
            status=data.status,
            raw=data.raw,
        )

        if data.started_at is not None:
            scrape_run.started_at = data.started_at

        self._session.add(scrape_run)
        self._session.flush()
        return scrape_run

    def finish(
        self,
        scrape_run: ScrapeRun,
        *,
        status: str,
        items_seen: int,
        items_saved: int,
        finished_at: datetime,
        error: str | None = None,
        raw: JsonObject | None = None,
    ) -> ScrapeRun:
        scrape_run.status = status
        scrape_run.items_seen = items_seen
        scrape_run.items_saved = items_saved
        scrape_run.finished_at = finished_at
        scrape_run.error = error
        if raw is not None:
            scrape_run.raw = raw

        self._session.flush()
        return scrape_run


class CanonicalProductRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, data: CanonicalProductCreate) -> CanonicalProduct:
        product = CanonicalProduct(
            title=data.title,
            normalized_title=data.normalized_title,
            category_id=data.category_id,
            brand=data.brand,
            model=data.model,
            unit_raw=data.unit_raw,
            attributes=data.attributes,
            match_status=data.match_status,
        )
        self._session.add(product)
        self._session.flush()
        return product

    def get(self, product_id: int) -> CanonicalProduct | None:
        return self._session.get(CanonicalProduct, product_id)

    def list_by_normalized_title(self, normalized_title: str) -> list[CanonicalProduct]:
        statement = (
            select(CanonicalProduct)
            .where(CanonicalProduct.normalized_title == normalized_title)
            .order_by(CanonicalProduct.id.asc())
        )
        return list(self._session.scalars(statement))


class ProductMatchRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, data: ProductMatchCreate) -> ProductMatch:
        _validate_product_match_status(data.status)
        match = ProductMatch(
            canonical_product_id=data.canonical_product_id,
            source_product_id=data.source_product_id,
            confidence=data.confidence,
            status=data.status,
            method=data.method,
            reviewed_at=data.reviewed_at,
            reviewed_by=data.reviewed_by,
            reason=data.reason,
        )
        if data.matched_at is not None:
            match.matched_at = data.matched_at

        self._session.add(match)
        self._session.flush()
        return match

    def get(self, match_id: int) -> ProductMatch | None:
        return self._session.get(ProductMatch, match_id)

    def list(
        self,
        *,
        status: str | None = None,
        canonical_product_id: int | None = None,
        source_product_id: int | None = None,
        limit: int | None = None,
    ) -> list[ProductMatch]:
        if status is not None:
            _validate_product_match_status(status)

        statement = select(ProductMatch).order_by(
            ProductMatch.confidence.desc(),
            ProductMatch.id.asc(),
        )
        if status is not None:
            statement = statement.where(ProductMatch.status == status)
        if canonical_product_id is not None:
            statement = statement.where(ProductMatch.canonical_product_id == canonical_product_id)
        if source_product_id is not None:
            statement = statement.where(ProductMatch.source_product_id == source_product_id)
        if limit is not None:
            statement = statement.limit(limit)

        return list(self._session.scalars(statement))

    def update_status(
        self,
        match: ProductMatch,
        *,
        status: str,
        reviewed_at: datetime | None = None,
        reviewed_by: str | None = None,
        reason: JsonObject | None = None,
    ) -> ProductMatch:
        _validate_product_match_status(status)
        match.status = status
        if reviewed_at is not None:
            match.reviewed_at = reviewed_at
        if reviewed_by is not None:
            match.reviewed_by = reviewed_by
        if reason is not None:
            match.reason = reason

        self._session.flush()
        return match


class OperatorDecisionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, data: OperatorDecisionCreate) -> OperatorDecision:
        decision_type = _validated_operator_decision_type(data.decision_type)
        action = _normalized_required_text(data.action, field="action")
        entity_type = _normalized_required_text(data.entity_type, field="entity_type")
        decision = OperatorDecision(
            decision_type=decision_type,
            action=action,
            entity_type=entity_type,
            entity_id=data.entity_id,
            source_product_id=data.source_product_id,
            canonical_product_id=data.canonical_product_id,
            product_match_id=data.product_match_id,
            category_id=data.category_id,
            actor=_normalized_optional_text(data.actor),
            reason=_normalized_optional_text(data.reason),
            previous_state=data.previous_state,
            new_state=data.new_state,
            evidence=data.evidence,
            alternatives=data.alternatives,
            decision_metadata=data.metadata,
        )
        if data.decided_at is not None:
            decision.decided_at = data.decided_at

        self._session.add(decision)
        self._session.flush()
        return decision

    def get(self, decision_id: int) -> OperatorDecision | None:
        return self._session.get(OperatorDecision, decision_id)

    def list(self, filters: OperatorDecisionFilters) -> list[OperatorDecision]:
        statement = _operator_decision_statement(filters).order_by(
            OperatorDecision.decided_at.desc(),
            OperatorDecision.id.desc(),
        )
        if filters.offset:
            statement = statement.offset(filters.offset)
        if filters.limit is not None:
            statement = statement.limit(filters.limit)
        return list(self._session.scalars(statement))

    def count(self, filters: OperatorDecisionFilters) -> int:
        statement = select(func.count()).select_from(
            _operator_decision_statement(filters).subquery()
        )
        return int(self._session.scalar(statement) or 0)


def _operator_decision_statement(filters: OperatorDecisionFilters) -> Any:
    statement = select(OperatorDecision)
    if filters.decision_type is not None:
        statement = statement.where(
            OperatorDecision.decision_type
            == _validated_operator_decision_type(filters.decision_type)
        )
    if filters.action is not None:
        statement = statement.where(
            OperatorDecision.action == _normalized_required_text(filters.action, field="action")
        )
    if filters.actor is not None:
        statement = statement.where(
            OperatorDecision.actor == _normalized_optional_text(filters.actor)
        )
    if filters.source_product_id is not None:
        statement = statement.where(
            OperatorDecision.source_product_id == filters.source_product_id
        )
    if filters.canonical_product_id is not None:
        statement = statement.where(
            OperatorDecision.canonical_product_id == filters.canonical_product_id
        )
    if filters.product_match_id is not None:
        statement = statement.where(
            OperatorDecision.product_match_id == filters.product_match_id
        )
    if filters.category_id is not None:
        statement = statement.where(OperatorDecision.category_id == filters.category_id)
    return statement


def _validate_product_match_status(status: str) -> None:
    if status not in PRODUCT_MATCH_STATUSES:
        allowed = ", ".join(sorted(PRODUCT_MATCH_STATUSES))
        raise ValueError(f"unknown product match status {status!r}; expected one of: {allowed}")


def _validated_operator_decision_type(decision_type: str) -> str:
    normalized = _normalized_required_text(decision_type, field="decision_type").lower()
    if normalized not in OPERATOR_DECISION_TYPES:
        allowed = ", ".join(sorted(OPERATOR_DECISION_TYPES))
        raise ValueError(
            f"unknown operator decision type {normalized!r}; expected one of: {allowed}"
        )
    return normalized


def _validated_source_type(source_type: str | None, *, source: str) -> str:
    selected = source_type.strip() if source_type is not None else _DEFAULT_SOURCE_TYPES.get(source)
    if not selected:
        selected = "official_html"
    if selected not in SHOP_SOURCE_TYPES:
        allowed = ", ".join(sorted(SHOP_SOURCE_TYPES))
        raise ValueError(f"unknown shop source type {selected!r}; expected one of: {allowed}")
    return selected


def _validate_shop_identity_status(status: str) -> None:
    if status not in SHOP_IDENTITY_STATUSES:
        allowed = ", ".join(sorted(SHOP_IDENTITY_STATUSES))
        raise ValueError(f"unknown shop identity status {status!r}; expected one of: {allowed}")


def _normalize_preferred_source(preferred_source: str | None) -> str | None:
    if preferred_source is None:
        return None

    normalized = preferred_source.strip()
    if not normalized:
        return None
    if normalized == "manual":
        raise ValueError("manual is not an accepted shop source")
    return normalized
