from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from stroyhub.catalog.categorization import RuleBasedCategorizer
from stroyhub.db.repositories import (
    CategoryRepository,
    CategoryUpsert,
    PriceSnapshotCreate,
    PriceSnapshotRepository,
    ScrapeRunCreate,
    ScrapeRunRepository,
    ShopRepository,
    ShopUpsert,
    SourceProductRepository,
    SourceProductUpsert,
)
from stroyhub.models import Shop
from stroyhub.parsers.common import JsonObject, ParsedProduct
from stroyhub.parsers.unicom import (
    UNICOM_DEFAULT_SHOP_SOURCE_ID,
    UNICOM_SOURCE,
    UnicomClient,
    UnicomProductsResult,
    parse_products,
)

UNICOM_DEFAULT_SHOP_NAME = "Юником"
UNICOM_DEFAULT_SHOP_URL = "https://unicom-ykt.ru/"
UNICOM_DEFAULT_LIMIT = 100
UNICOM_DEFAULT_MAX_PAGES = 100
UNICOM_DEFAULT_SORT = "popular"
UNICOM_DEFAULT_CATEGORIES_PER_RUN = 1000
UNICOM_CATEGORY_BATCH_RAW_KEY = "unicom_category_batch"
UNICOM_DEFAULT_CATEGORY_UUIDS = (
    "fac247f1ae6111eca255000c29d1f857",
    "d68e4fb83d4d11e8af077062b8b53ba3",
    "a975a5d53d4d11e8af077062b8b53ba3",
    "46d377c7807811eaa229000c29d1f857",
    "ef6197bd3e1911e886f37062b8b53ba3",
    "c7d676b1bbcf11eca256000c29d1f857",
)


@dataclass(frozen=True, kw_only=True)
class UnicomScrapeResult:
    category_uuid: str
    shop_source_id: str
    limit: int
    sort: str
    pages_seen: int
    products_seen: int
    products_count: int | None
    products: list[ParsedProduct]
    completeness: str
    stop_reason: str
    product_result: UnicomProductsResult


@dataclass(frozen=True, kw_only=True)
class UnicomPersistResult:
    shop_id: int
    scrape_run_id: int
    source_products_saved: int
    price_snapshots_saved: int
    scrape_status: str


@dataclass(frozen=True, kw_only=True)
class UnicomShopScrapeConfig:
    category_uuids: tuple[str, ...]
    limit: int = UNICOM_DEFAULT_LIMIT
    sort: str = UNICOM_DEFAULT_SORT
    max_pages: int = UNICOM_DEFAULT_MAX_PAGES
    categories_per_run: int = UNICOM_DEFAULT_CATEGORIES_PER_RUN


@dataclass(frozen=True, kw_only=True)
class UnicomCategoryBatchState:
    enabled: bool
    total: int
    next_index: int
    categories_seen: int
    categories_per_run: int
    completed: bool
    total_products: int | None = None
    last_stop_reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class UnicomShopScrapeResult:
    shop_id: int
    categories_seen: int
    categories_total: int
    categories_partial: int
    products_seen: int
    source_products_saved: int
    price_snapshots_saved: int
    scrape_status: str
    batch_progress: bool


def scrape_unicom_category(
    *,
    category_uuid: str,
    client: UnicomClient | None = None,
    shop_source_id: str = UNICOM_DEFAULT_SHOP_SOURCE_ID,
    limit: int = UNICOM_DEFAULT_LIMIT,
    sort: str = "popular",
    max_pages: int = 100,
    parsed_at: datetime | None = None,
) -> UnicomScrapeResult:
    unicom_client = client or UnicomClient()
    product_result = unicom_client.fetch_category_products(
        category_uuid=category_uuid,
        limit=limit,
        sort=sort,
        shop=shop_source_id,
        max_pages=max_pages,
    )
    observed_at = parsed_at or datetime.now(UTC)
    products = parse_products(
        product_result.products,
        shop_source_id=shop_source_id,
        parsed_at=observed_at,
    )

    return UnicomScrapeResult(
        category_uuid=category_uuid,
        shop_source_id=shop_source_id,
        limit=limit,
        sort=sort,
        pages_seen=len(product_result.pages),
        products_seen=len(product_result.products),
        products_count=product_result.products_count,
        products=products,
        completeness=product_result.completeness,
        stop_reason=product_result.stop_reason,
        product_result=product_result,
    )


def scrape_unicom_shop(
    session: Session,
    shop: Shop,
    *,
    client: UnicomClient | None = None,
    finished_at: datetime | None = None,
) -> UnicomShopScrapeResult:
    completed_at = finished_at or datetime.now(UTC)
    config = unicom_shop_scrape_config(shop.raw)
    category_uuids, start_index, batch_enabled = _category_batch_window(
        config=config,
        raw=shop.raw,
    )
    categories_partial = 0
    products_seen = 0
    source_products_saved = 0
    price_snapshots_saved = 0
    category_product_counts = _category_product_counts(shop.raw)

    for category_uuid in category_uuids:
        result = scrape_unicom_category(
            category_uuid=category_uuid,
            client=client,
            shop_source_id=shop.source_id,
            limit=config.limit,
            sort=config.sort,
            max_pages=config.max_pages,
            parsed_at=completed_at,
        )
        persisted = persist_unicom_scrape_result(
            session,
            result,
            shop_name=shop.name,
            shop_url=shop.url or UNICOM_DEFAULT_SHOP_URL,
            finished_at=completed_at,
        )
        products_seen += result.products_seen
        source_products_saved += persisted.source_products_saved
        price_snapshots_saved += persisted.price_snapshots_saved
        if result.products_count is not None:
            category_product_counts[category_uuid] = result.products_count
        if persisted.scrape_status != "success":
            categories_partial += 1

    next_index = start_index + len(category_uuids)
    completed = next_index >= len(config.category_uuids)
    scrape_status = "partial" if categories_partial or not completed else "success"
    refreshed_shop = session.get(Shop, shop.id)
    if refreshed_shop is not None:
        raw = dict(refreshed_shop.raw or {})
        raw[UNICOM_CATEGORY_BATCH_RAW_KEY] = build_unicom_category_batch_raw(
            enabled=batch_enabled,
            total=len(config.category_uuids),
            next_index=0 if completed else next_index,
            categories_seen=next_index,
            categories_per_run=config.categories_per_run,
            completed=completed,
            category_product_counts=category_product_counts,
            last_stop_reason="all_categories_seen" if completed else "category_batch_limit",
        )
        refreshed_shop.raw = raw

    return UnicomShopScrapeResult(
        shop_id=shop.id,
        categories_seen=len(category_uuids),
        categories_total=len(config.category_uuids),
        categories_partial=categories_partial,
        products_seen=products_seen,
        source_products_saved=source_products_saved,
        price_snapshots_saved=price_snapshots_saved,
        scrape_status=scrape_status,
        batch_progress=batch_enabled and not categories_partial,
    )


def persist_unicom_scrape_result(
    session: Session,
    result: UnicomScrapeResult,
    *,
    shop_name: str = "Юником",
    shop_url: str = "https://unicom-ykt.ru/",
    finished_at: datetime | None = None,
) -> UnicomPersistResult:
    completed_at = finished_at or datetime.now(UTC)
    scrape_run_status = "success" if result.completeness in {"complete", "empty"} else "partial"
    shop_status = "success" if scrape_run_status == "success" else "failed"

    shop_repository = ShopRepository(session)
    existing_shop = shop_repository.get_by_source_id(
        source=UNICOM_SOURCE,
        source_id=result.shop_source_id,
    )
    raw = dict(existing_shop.raw or {}) if existing_shop is not None else {}
    raw.update(_shop_raw(result))

    shop = shop_repository.upsert(
        ShopUpsert(
            source=UNICOM_SOURCE,
            source_id=result.shop_source_id,
            source_type="official_api",
            name=shop_name,
            url=shop_url,
            raw=raw,
            last_scraped_at=completed_at,
            scrape_status=shop_status,
        )
    )
    scrape_run_repository = ScrapeRunRepository(session)
    scrape_run = scrape_run_repository.start(
        ScrapeRunCreate(
            source=UNICOM_SOURCE,
            shop_id=shop.id,
            started_at=_first_parsed_at(result.products) or completed_at,
            raw=_scrape_run_raw(result),
        )
    )

    product_repository = SourceProductRepository(session)
    price_repository = PriceSnapshotRepository(session)
    category_repository = CategoryRepository(session)
    categorizer = RuleBasedCategorizer()
    source_products_saved = 0
    price_snapshots_saved = 0

    for product in result.products:
        category_id = _category_id(
            category_repository=category_repository,
            categorizer=categorizer,
            product=product,
        )

        source_product = product_repository.upsert(
            SourceProductUpsert(
                shop_id=shop.id,
                source=product.source,
                source_product_id=product.source_product_id,
                fingerprint=product.fingerprint,
                title=product.title,
                normalized_title=product.normalized_title,
                description=product.description,
                category_id=category_id,
                category_raw=product.category_raw,
                unit_raw=product.unit_raw,
                image_url=product.image_url,
                source_updated_at=product.source_updated_at,
                raw=product.raw,
                observed_at=product.parsed_at,
            )
        )
        source_products_saved += 1

        price_repository.add(
            PriceSnapshotCreate(
                source_product_id=source_product.id,
                price=product.price,
                currency=product.currency,
                unit_raw=product.unit_raw,
                source_updated_at=product.source_updated_at,
                parsed_at=product.parsed_at,
                raw=product.raw,
            )
        )
        price_snapshots_saved += 1

    scrape_run_repository.finish(
        scrape_run,
        status=scrape_run_status,
        items_seen=result.products_seen,
        items_saved=source_products_saved,
        finished_at=completed_at,
        raw=_scrape_run_raw(result),
    )

    return UnicomPersistResult(
        shop_id=shop.id,
        scrape_run_id=scrape_run.id,
        source_products_saved=source_products_saved,
        price_snapshots_saved=price_snapshots_saved,
        scrape_status=scrape_run_status,
    )


def persist_unicom_scrape_failure(
    session: Session,
    shop: Shop,
    *,
    error: str,
    failed_at: datetime | None = None,
) -> int:
    completed_at = failed_at or datetime.now(UTC)
    raw = {
        "source": UNICOM_SOURCE,
        "shop_source_id": shop.source_id,
        "shop_scrape": True,
        "config": unicom_shop_scrape_config(shop.raw).__dict__,
    }
    scrape_run_repository = ScrapeRunRepository(session)
    scrape_run = scrape_run_repository.start(
        ScrapeRunCreate(
            source=UNICOM_SOURCE,
            shop_id=shop.id,
            started_at=completed_at,
            raw=raw,
        )
    )
    scrape_run_repository.finish(
        scrape_run,
        status="failed",
        items_seen=0,
        items_saved=0,
        finished_at=completed_at,
        error=error,
        raw={**raw, "error": error},
    )
    return scrape_run.id


def unicom_shop_scrape_config(raw: JsonObject | None) -> UnicomShopScrapeConfig:
    config = raw or {}
    category_uuids = _string_tuple(config.get("category_uuids"))
    if not category_uuids:
        category_uuids = UNICOM_DEFAULT_CATEGORY_UUIDS

    return UnicomShopScrapeConfig(
        category_uuids=category_uuids,
        limit=_positive_int(config.get("limit"), default=UNICOM_DEFAULT_LIMIT),
        sort=str(config.get("sort") or UNICOM_DEFAULT_SORT),
        max_pages=_positive_int(config.get("max_pages"), default=UNICOM_DEFAULT_MAX_PAGES),
        categories_per_run=_positive_int(
            config.get("categories_per_run"),
            default=UNICOM_DEFAULT_CATEGORIES_PER_RUN,
        ),
    )


def unicom_category_batch_state(raw: JsonObject | None) -> UnicomCategoryBatchState | None:
    if not isinstance(raw, dict):
        return None
    value = raw.get(UNICOM_CATEGORY_BATCH_RAW_KEY)
    if not isinstance(value, dict):
        return None
    total = max(_positive_int(value.get("total"), default=0), 0)
    categories_per_run = _positive_int(
        value.get("categories_per_run"),
        default=UNICOM_DEFAULT_CATEGORIES_PER_RUN,
    )
    return UnicomCategoryBatchState(
        enabled=bool(value.get("enabled")),
        total=total,
        next_index=max(_positive_int(value.get("next_index"), default=0), 0),
        categories_seen=max(_positive_int(value.get("categories_seen"), default=0), 0),
        categories_per_run=categories_per_run,
        completed=bool(value.get("completed")),
        total_products=_optional_int(value.get("total_products")),
        last_stop_reason=value.get("last_stop_reason")
        if isinstance(value.get("last_stop_reason"), str)
        else None,
    )


def build_unicom_category_batch_raw(
    *,
    enabled: bool,
    total: int,
    next_index: int = 0,
    categories_seen: int = 0,
    categories_per_run: int = UNICOM_DEFAULT_CATEGORIES_PER_RUN,
    completed: bool = False,
    category_product_counts: dict[str, int] | None = None,
    last_stop_reason: str | None = None,
) -> JsonObject:
    counts = dict(category_product_counts or {})
    return {
        "enabled": enabled,
        "total": total,
        "next_index": next_index,
        "categories_seen": categories_seen,
        "categories_per_run": categories_per_run,
        "completed": completed,
        "category_product_counts": counts,
        "total_products": sum(counts.values()) if counts else None,
        "last_stop_reason": last_stop_reason,
    }


def _category_batch_window(
    *,
    config: UnicomShopScrapeConfig,
    raw: JsonObject | None,
) -> tuple[tuple[str, ...], int, bool]:
    total = len(config.category_uuids)
    if total <= config.categories_per_run:
        return config.category_uuids, 0, False

    state = unicom_category_batch_state(raw)
    start_index = state.next_index if state is not None and state.enabled else 0
    if state is not None and state.completed:
        start_index = 0
    start_index = min(max(start_index, 0), total)
    if start_index >= total:
        start_index = 0

    end_index = min(start_index + config.categories_per_run, total)
    return config.category_uuids[start_index:end_index], start_index, True


def _category_product_counts(raw: JsonObject | None) -> dict[str, int]:
    state = raw.get(UNICOM_CATEGORY_BATCH_RAW_KEY) if isinstance(raw, dict) else None
    if not isinstance(state, dict):
        return {}
    counts = state.get("category_product_counts")
    if not isinstance(counts, dict):
        return {}
    return {
        key: value
        for key, value in counts.items()
        if isinstance(key, str) and isinstance(value, int) and value >= 0
    }


def _category_id(
    *,
    category_repository: CategoryRepository,
    categorizer: RuleBasedCategorizer,
    product: ParsedProduct,
) -> int | None:
    prediction = categorizer.categorize(
        title=product.title,
        source=product.source,
        category_raw=product.category_raw,
        description=product.description,
    )
    if prediction is None:
        return None

    parent_id = None
    if prediction.parent_slug is not None and prediction.parent_name is not None:
        parent = category_repository.upsert(
            CategoryUpsert(
                slug=prediction.parent_slug,
                name=prediction.parent_name,
            )
        )
        parent_id = parent.id

    category = category_repository.upsert(
        CategoryUpsert(
            slug=prediction.category_slug,
            name=prediction.category_name,
            parent_id=parent_id,
        )
    )
    return category.id


def _first_parsed_at(products: list[ParsedProduct]) -> datetime | None:
    if not products:
        return None
    return products[0].parsed_at


def _shop_raw(result: UnicomScrapeResult) -> JsonObject:
    return {
        "source": UNICOM_SOURCE,
        "shop_source_id": result.shop_source_id,
        "category_uuid": result.category_uuid,
        "pages_seen": result.pages_seen,
        "products_seen": result.products_seen,
        "products_count": result.products_count,
        "completeness": result.completeness,
        "stop_reason": result.stop_reason,
    }


def _scrape_run_raw(result: UnicomScrapeResult) -> JsonObject:
    return {
        "shop_source_id": result.shop_source_id,
        "category_uuid": result.category_uuid,
        "limit": result.limit,
        "sort": result.sort,
        "pages_seen": result.pages_seen,
        "products_seen": result.products_seen,
        "products_parsed": len(result.products),
        "products_count": result.products_count,
        "completeness": result.completeness,
        "stop_reason": result.stop_reason,
    }


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _positive_int(value: object, *, default: int) -> int:
    if not isinstance(value, int):
        return default
    if value < 1:
        return default
    return value


def _optional_int(value: object) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    return None
