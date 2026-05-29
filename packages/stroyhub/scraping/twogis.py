from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from stroyhub.catalog.product_suitability import ProductSuitabilityEvaluator
from stroyhub.catalog.source_category_mappings import categorizer_for_session
from stroyhub.db.repositories import (
    CategoryRepository,
    CategoryUpsert,
    PriceSnapshotRepository,
    ScrapeRunCreate,
    ScrapeRunRepository,
    ShopRepository,
    ShopUpsert,
    SourceProductRepository,
)
from stroyhub.parsers.common import JsonObject, ParsedProduct
from stroyhub.parsers.twogis import TwogisBranchItems, TwogisClient, parse_product_items
from stroyhub.scraping.source_products import persist_source_product_observation

TWOGIS_SOURCE = "2gis"
TWOGIS_LARGE_CATALOG_THRESHOLD = 2_000
TWOGIS_LARGE_CATALOG_PAGE_SIZE = 50
TWOGIS_LARGE_CATALOG_PAGES_PER_RUN = 40
TWOGIS_LARGE_CATALOG_RAW_KEY = "twogis_large_catalog"


@dataclass(frozen=True, kw_only=True)
class TwogisScrapeResult:
    branch_id: str
    start_page: int
    page_size: int
    total: int | None
    pages_seen: int
    items_seen: int
    pinned_items_seen: int
    products: list[ParsedProduct]
    completeness: str
    stop_reason: str
    branch_items: TwogisBranchItems


@dataclass(frozen=True, kw_only=True)
class TwogisPersistResult:
    shop_id: int
    scrape_run_id: int
    source_products_saved: int
    price_snapshots_saved: int
    scrape_status: str


@dataclass(frozen=True, kw_only=True)
class TwogisLargeCatalogState:
    enabled: bool
    threshold: int
    total: int | None
    page_size: int
    pages_per_run: int
    next_page: int
    items_loaded: int
    completed: bool
    last_stop_reason: str | None = None


def scrape_twogis_branch(
    *,
    branch_id: str,
    client: TwogisClient | None = None,
    start_page: int = 1,
    page_size: int = 50,
    max_pages: int = 100,
    locale: str = "ru_RU",
    parsed_at: datetime | None = None,
) -> TwogisScrapeResult:
    twogis_client = client or TwogisClient()
    if start_page == 1:
        branch_items = twogis_client.fetch_branch_items(
            branch_id=branch_id,
            page_size=page_size,
            max_pages=max_pages,
            locale=locale,
        )
    else:
        branch_items = twogis_client.fetch_branch_items_window(
            branch_id=branch_id,
            start_page=start_page,
            page_size=page_size,
            max_pages=max_pages,
            locale=locale,
            limit_stop_reason="large_catalog_batch_limit",
        )
    observed_at = parsed_at or datetime.now(UTC)

    products = parse_product_items(
        branch_items.items,
        branch_id=branch_id,
        source_updated_at_raw=_first_updated_at(branch_items),
        parsed_at=observed_at,
    )

    return TwogisScrapeResult(
        branch_id=branch_id,
        start_page=start_page,
        page_size=page_size,
        total=branch_items.total,
        pages_seen=len(branch_items.pages),
        items_seen=len(branch_items.items),
        pinned_items_seen=len(branch_items.pinned_items),
        products=products,
        completeness=branch_items.completeness,
        stop_reason=branch_items.stop_reason,
        branch_items=branch_items,
    )


def twogis_large_catalog_state(raw: JsonObject | None) -> TwogisLargeCatalogState | None:
    if not isinstance(raw, dict):
        return None
    value = raw.get(TWOGIS_LARGE_CATALOG_RAW_KEY)
    if not isinstance(value, dict):
        return None
    return TwogisLargeCatalogState(
        enabled=bool(value.get("enabled")),
        threshold=_int_value(value.get("threshold"), TWOGIS_LARGE_CATALOG_THRESHOLD),
        total=_optional_int_value(value.get("total")),
        page_size=_int_value(value.get("page_size"), TWOGIS_LARGE_CATALOG_PAGE_SIZE),
        pages_per_run=_int_value(value.get("pages_per_run"), TWOGIS_LARGE_CATALOG_PAGES_PER_RUN),
        next_page=max(_int_value(value.get("next_page"), 1), 1),
        items_loaded=max(_int_value(value.get("items_loaded"), 0), 0),
        completed=bool(value.get("completed")),
        last_stop_reason=value.get("last_stop_reason")
        if isinstance(value.get("last_stop_reason"), str)
        else None,
    )


def build_twogis_large_catalog_raw(
    *,
    enabled: bool,
    total: int | None,
    next_page: int = 1,
    items_loaded: int = 0,
    completed: bool = False,
    threshold: int = TWOGIS_LARGE_CATALOG_THRESHOLD,
    page_size: int = TWOGIS_LARGE_CATALOG_PAGE_SIZE,
    pages_per_run: int = TWOGIS_LARGE_CATALOG_PAGES_PER_RUN,
    last_stop_reason: str | None = None,
) -> JsonObject:
    return {
        "enabled": enabled,
        "threshold": threshold,
        "total": total,
        "page_size": page_size,
        "pages_per_run": pages_per_run,
        "next_page": next_page,
        "items_loaded": items_loaded,
        "completed": completed,
        "last_stop_reason": last_stop_reason,
    }


def update_twogis_large_catalog_progress(
    raw: JsonObject | None,
    result: TwogisScrapeResult,
) -> JsonObject:
    existing = dict(raw or {})
    state = twogis_large_catalog_state(existing)
    page_size = state.page_size if state is not None else TWOGIS_LARGE_CATALOG_PAGE_SIZE
    pages_per_run = (
        state.pages_per_run if state is not None else TWOGIS_LARGE_CATALOG_PAGES_PER_RUN
    )
    previous_loaded = state.items_loaded if state is not None else 0
    if state is not None and state.completed and result.start_page == 1:
        previous_loaded = 0
    fetched_until = (result.start_page - 1) * result.page_size + result.items_seen
    items_loaded = max(previous_loaded, fetched_until)
    total = (
        result.total
        if result.total is not None
        else (state.total if state is not None else None)
    )
    completed = result.completeness in {"complete", "empty"} or (
        total is not None and items_loaded >= total
    )
    next_page = 1 if completed else result.start_page + result.pages_seen
    existing[TWOGIS_LARGE_CATALOG_RAW_KEY] = build_twogis_large_catalog_raw(
        enabled=state.enabled if state is not None else True,
        total=total,
        next_page=next_page,
        items_loaded=items_loaded,
        completed=completed,
        threshold=state.threshold if state is not None else TWOGIS_LARGE_CATALOG_THRESHOLD,
        page_size=page_size,
        pages_per_run=pages_per_run,
        last_stop_reason=result.stop_reason,
    )
    return existing


def persist_twogis_scrape_result(
    session: Session,
    result: TwogisScrapeResult,
    *,
    shop_name: str | None = None,
    finished_at: datetime | None = None,
    partial_shop_status: str = "failed",
    suitability_evaluator: ProductSuitabilityEvaluator | None = None,
) -> TwogisPersistResult:
    completed_at = finished_at or datetime.now(UTC)
    scrape_run_status = "success" if result.completeness in {"complete", "empty"} else "partial"
    shop_status = "success" if scrape_run_status == "success" else partial_shop_status
    existing_shop = ShopRepository(session).get_by_source_id(
        source=TWOGIS_SOURCE,
        source_id=result.branch_id,
    )
    raw = dict(existing_shop.raw or {}) if existing_shop is not None else {}
    raw.update(_shop_raw(result))

    shop = ShopRepository(session).upsert(
        ShopUpsert(
            source=TWOGIS_SOURCE,
            source_id=result.branch_id,
            source_type="2gis",
            name=shop_name or f"2GIS branch {result.branch_id}",
            raw=raw,
            last_scraped_at=completed_at,
            scrape_status=shop_status,
        )
    )
    scrape_run_repository = ScrapeRunRepository(session)
    scrape_run = scrape_run_repository.start(
        ScrapeRunCreate(
            source=TWOGIS_SOURCE,
            shop_id=shop.id,
            started_at=_first_parsed_at(result.products) or completed_at,
            raw=_scrape_run_raw(result),
        )
    )

    product_repository = SourceProductRepository(session)
    price_repository = PriceSnapshotRepository(session)
    category_repository = CategoryRepository(session)
    categorizer = categorizer_for_session(session)
    suitability_evaluator = suitability_evaluator or ProductSuitabilityEvaluator.default()
    source_products_saved = 0
    price_snapshots_saved = 0

    for product in result.products:
        category_id = None
        prediction = categorizer.categorize(
            title=product.title,
            source=product.source,
            category_raw=product.category_raw,
            description=product.description,
        )
        if prediction is not None:
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
            category_id = category.id

        persist_source_product_observation(
            product_repository=product_repository,
            price_repository=price_repository,
            suitability_evaluator=suitability_evaluator,
            shop_id=shop.id,
            product=product,
            category_id=category_id,
        )
        source_products_saved += 1
        price_snapshots_saved += 1

    scrape_run_repository.finish(
        scrape_run,
        status=scrape_run_status,
        items_seen=result.items_seen,
        items_saved=source_products_saved,
        finished_at=completed_at,
        raw=_scrape_run_raw(result),
    )

    return TwogisPersistResult(
        shop_id=shop.id,
        scrape_run_id=scrape_run.id,
        source_products_saved=source_products_saved,
        price_snapshots_saved=price_snapshots_saved,
        scrape_status=scrape_run_status,
    )


def _first_updated_at(result: TwogisBranchItems) -> str | None:
    for page in result.pages:
        if page.updated_at_raw is not None:
            return page.updated_at_raw
    return None


def _first_parsed_at(products: list[ParsedProduct]) -> datetime | None:
    if not products:
        return None
    return products[0].parsed_at


def _shop_raw(result: TwogisScrapeResult) -> JsonObject:
    return {
        "source": TWOGIS_SOURCE,
        "branch_id": result.branch_id,
        "start_page": result.start_page,
        "total": result.total,
        "pages_seen": result.pages_seen,
        "items_seen": result.items_seen,
        "pinned_items_seen": result.pinned_items_seen,
        "completeness": result.completeness,
        "stop_reason": result.stop_reason,
    }


def _scrape_run_raw(result: TwogisScrapeResult) -> JsonObject:
    return {
        "branch_id": result.branch_id,
        "start_page": result.start_page,
        "page_size": result.page_size,
        "total": result.total,
        "pages_seen": result.pages_seen,
        "items_seen": result.items_seen,
        "products_parsed": len(result.products),
        "pinned_items_seen": result.pinned_items_seen,
        "completeness": result.completeness,
        "stop_reason": result.stop_reason,
    }


def _int_value(value: object, fallback: int) -> int:
    return value if isinstance(value, int) else fallback


def _optional_int_value(value: object) -> int | None:
    return value if isinstance(value, int) else None
