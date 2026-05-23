from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
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
from stroyhub.models import Shop, SourceProduct
from stroyhub.parsers.common import JsonObject, ParsedProduct, build_fingerprint
from stroyhub.parsers.metalltorg import (
    METALLTORG_BASE_URL,
    METALLTORG_SHOP_SOURCE_ID,
    METALLTORG_SOURCE,
    parse_listing_page,
    parse_product_detail_page,
)

METALLTORG_DEFAULT_SHOP_NAME = "Металл Торг"
METALLTORG_DEFAULT_SHOP_URL = METALLTORG_BASE_URL
METALLTORG_DEFAULT_TIMEOUT = 20.0
METALLTORG_DEFAULT_MAX_PAGES = 60
METALLTORG_DEFAULT_CATEGORY_URLS = (
    f"{METALLTORG_BASE_URL}/catalog/stroitelnye_materialy_1/",
)


@dataclass(frozen=True, kw_only=True)
class MetalltorgScrapeResult:
    start_url: str
    pages_seen: int
    products_seen: int
    priced_products: int
    total_count: int | None
    products: list[ParsedProduct]
    completeness: str
    stop_reason: str
    failures: int
    next_pages_seen: int


@dataclass(frozen=True, kw_only=True)
class MetalltorgPersistResult:
    shop_id: int
    scrape_run_id: int
    source_products_saved: int
    price_snapshots_saved: int
    scrape_status: str


@dataclass(frozen=True, kw_only=True)
class MetalltorgShopScrapeConfig:
    category_urls: tuple[str, ...]
    max_pages: int = METALLTORG_DEFAULT_MAX_PAGES
    timeout: float = METALLTORG_DEFAULT_TIMEOUT
    detail_enrichment: bool = True


@dataclass(frozen=True, kw_only=True)
class MetalltorgShopScrapeResult:
    shop_id: int
    categories_seen: int
    categories_partial: int
    products_seen: int
    source_products_saved: int
    price_snapshots_saved: int
    scrape_status: str
    details_fetched: int = 0


def scrape_metalltorg_category(
    *,
    start_url: str,
    max_pages: int = METALLTORG_DEFAULT_MAX_PAGES,
    timeout: float = METALLTORG_DEFAULT_TIMEOUT,
    fetch: Callable[[str, float], str] | None = None,
    parsed_at: datetime | None = None,
) -> MetalltorgScrapeResult:
    fetch_html = fetch or _fetch_html
    observed_at = parsed_at or datetime.now(UTC)
    seen_urls: set[str] = set()
    pending_urls = [start_url]
    products: list[ParsedProduct] = []
    pages_seen = 0
    priced_products = 0
    failures = 0
    next_pages_seen = 0
    total_count: int | None = None

    while pending_urls and pages_seen < max_pages:
        url = pending_urls.pop(0)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        try:
            html = fetch_html(url, timeout)
        except httpx.HTTPError:
            failures += 1
            continue

        page = parse_listing_page(html, page_url=url, parsed_at=observed_at)
        pages_seen += 1
        products.extend(page.products)
        priced_products += sum(1 for product in page.products if product.price is not None)
        total_count = page.total_count if page.total_count is not None else total_count
        if _has_seen_reported_total(products_seen=len(products), total_count=total_count):
            pending_urls.clear()
            break

        for next_url in page.next_page_urls:
            if next_url not in seen_urls and next_url not in pending_urls:
                pending_urls.append(next_url)
                next_pages_seen += 1

    completeness = "complete"
    stop_reason = "complete"
    if pending_urls:
        completeness = "partial"
        stop_reason = "max_pages_reached"
    if failures:
        completeness = "partial"
        stop_reason = "page_failures"

    return MetalltorgScrapeResult(
        start_url=start_url,
        pages_seen=pages_seen,
        products_seen=len(products),
        priced_products=priced_products,
        total_count=total_count,
        products=products,
        completeness=completeness,
        stop_reason=stop_reason,
        failures=failures,
        next_pages_seen=next_pages_seen,
    )


def scrape_metalltorg_shop(
    session: Session,
    shop: Shop,
    *,
    fetch: Callable[[str, float], str] | None = None,
    finished_at: datetime | None = None,
) -> MetalltorgShopScrapeResult:
    completed_at = finished_at or datetime.now(UTC)
    config = metalltorg_shop_scrape_config(shop.raw)
    categories_partial = 0
    products_seen = 0
    source_products_saved = 0
    price_snapshots_saved = 0
    details_fetched = 0

    for category_url in config.category_urls:
        result = scrape_metalltorg_category(
            start_url=category_url,
            max_pages=config.max_pages,
            timeout=config.timeout,
            fetch=fetch,
            parsed_at=completed_at,
        )
        result, category_details_fetched = enrich_metalltorg_category_details(
            session,
            shop,
            result,
            enabled=config.detail_enrichment,
            fetch=fetch,
            timeout=config.timeout,
        )
        persisted = persist_metalltorg_scrape_result(
            session,
            result,
            shop_name=shop.name,
            shop_url=shop.url or METALLTORG_DEFAULT_SHOP_URL,
            finished_at=completed_at,
        )
        products_seen += result.products_seen
        source_products_saved += persisted.source_products_saved
        price_snapshots_saved += persisted.price_snapshots_saved
        details_fetched += category_details_fetched
        if persisted.scrape_status != "success":
            categories_partial += 1

    scrape_status = "partial" if categories_partial else "success"
    return MetalltorgShopScrapeResult(
        shop_id=shop.id,
        categories_seen=len(config.category_urls),
        categories_partial=categories_partial,
        products_seen=products_seen,
        source_products_saved=source_products_saved,
        price_snapshots_saved=price_snapshots_saved,
        scrape_status=scrape_status,
        details_fetched=details_fetched,
    )


def enrich_metalltorg_category_details(
    session: Session,
    shop: Shop,
    result: MetalltorgScrapeResult,
    *,
    enabled: bool = True,
    fetch: Callable[[str, float], str] | None = None,
    timeout: float = METALLTORG_DEFAULT_TIMEOUT,
) -> tuple[MetalltorgScrapeResult, int]:
    if not enabled or not result.products:
        return result, 0

    fetch_html = fetch or _fetch_html
    enriched_products: list[ParsedProduct] = []
    details_fetched = 0

    for product in result.products:
        if not _needs_detail_enrichment(session, shop_id=shop.id, product=product):
            enriched_products.append(product)
            continue

        product_url = product.raw.get("product_url")
        if not isinstance(product_url, str) or not product_url.strip():
            enriched_products.append(product)
            continue

        try:
            detail_html = fetch_html(product_url, timeout)
        except httpx.HTTPError:
            enriched_products.append(product)
            continue

        detail = parse_product_detail_page(detail_html, page_url=product_url)
        details_fetched += 1
        category_raw = detail.category_raw or product.category_raw
        detail_raw = {
            **product.raw,
            "detail": detail.raw,
            "detail_enriched": bool(detail.category_raw),
        }
        enriched_products.append(
            replace(
                product,
                category_raw=category_raw,
                description=detail.description or product.description,
                fingerprint=build_fingerprint(
                    product.normalized_title,
                    product.unit_raw,
                    category_raw,
                ),
                raw=detail_raw,
            )
        )

    return replace(result, products=enriched_products), details_fetched


def persist_metalltorg_scrape_result(
    session: Session,
    result: MetalltorgScrapeResult,
    *,
    shop_name: str = METALLTORG_DEFAULT_SHOP_NAME,
    shop_url: str = METALLTORG_DEFAULT_SHOP_URL,
    finished_at: datetime | None = None,
) -> MetalltorgPersistResult:
    completed_at = finished_at or datetime.now(UTC)
    scrape_run_status = "success" if result.completeness == "complete" else "partial"
    shop_status = "success" if scrape_run_status == "success" else "failed"

    shop_repository = ShopRepository(session)
    existing_shop = shop_repository.get_by_source_id(
        source=METALLTORG_SOURCE,
        source_id=METALLTORG_SHOP_SOURCE_ID,
    )
    raw = dict(existing_shop.raw or {}) if existing_shop is not None else {}
    raw.update(_shop_raw(result))
    shop = shop_repository.upsert(
        ShopUpsert(
            source=METALLTORG_SOURCE,
            source_id=METALLTORG_SHOP_SOURCE_ID,
            source_type="official_html",
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
            source=METALLTORG_SOURCE,
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
        source_product = product_repository.upsert(
            SourceProductUpsert(
                shop_id=shop.id,
                source=product.source,
                source_product_id=product.source_product_id,
                fingerprint=product.fingerprint,
                title=product.title,
                normalized_title=product.normalized_title,
                description=product.description,
                category_id=_category_id(
                    category_repository=category_repository,
                    categorizer=categorizer,
                    product=product,
                ),
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

    return MetalltorgPersistResult(
        shop_id=shop.id,
        scrape_run_id=scrape_run.id,
        source_products_saved=source_products_saved,
        price_snapshots_saved=price_snapshots_saved,
        scrape_status=scrape_run_status,
    )


def persist_metalltorg_scrape_failure(
    session: Session,
    shop: Shop,
    *,
    error: str,
    failed_at: datetime | None = None,
) -> int:
    completed_at = failed_at or datetime.now(UTC)
    raw = {
        "source": METALLTORG_SOURCE,
        "shop_source_id": shop.source_id,
        "shop_scrape": True,
        "config": metalltorg_shop_scrape_config(shop.raw).__dict__,
    }
    scrape_run_repository = ScrapeRunRepository(session)
    scrape_run = scrape_run_repository.start(
        ScrapeRunCreate(
            source=METALLTORG_SOURCE,
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


def metalltorg_shop_scrape_config(raw: JsonObject | None) -> MetalltorgShopScrapeConfig:
    config = raw or {}
    category_urls = _string_tuple(config.get("category_urls"))
    if not category_urls:
        category_urls = METALLTORG_DEFAULT_CATEGORY_URLS

    return MetalltorgShopScrapeConfig(
        category_urls=category_urls,
        max_pages=_positive_int(config.get("max_pages"), default=METALLTORG_DEFAULT_MAX_PAGES),
        timeout=_positive_float(config.get("timeout"), default=METALLTORG_DEFAULT_TIMEOUT),
        detail_enrichment=bool(config.get("detail_enrichment", True)),
    )


def _needs_detail_enrichment(
    session: Session,
    *,
    shop_id: int,
    product: ParsedProduct,
) -> bool:
    if product.source_product_id is None:
        return not _has_detail_category(product.category_raw)

    existing = session.scalar(
        select(SourceProduct).where(
            SourceProduct.source == product.source,
            SourceProduct.shop_id == shop_id,
            SourceProduct.source_product_id == product.source_product_id,
        )
    )
    if existing is None:
        return True
    return not _has_detail_category(existing.category_raw)


def _has_detail_category(category_raw: str | None) -> bool:
    return bool(category_raw and "/" in category_raw)


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
            CategoryUpsert(slug=prediction.parent_slug, name=prediction.parent_name)
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


def _shop_raw(result: MetalltorgScrapeResult) -> JsonObject:
    return {
        "source": METALLTORG_SOURCE,
        "shop_source_id": METALLTORG_SHOP_SOURCE_ID,
        "start_url": result.start_url,
        "pages_seen": result.pages_seen,
        "products_seen": result.products_seen,
        "priced_products": result.priced_products,
        "total_count": result.total_count,
        "completeness": result.completeness,
        "stop_reason": result.stop_reason,
        "failures": result.failures,
    }


def _has_seen_reported_total(*, products_seen: int, total_count: int | None) -> bool:
    return total_count is not None and products_seen >= total_count


def _scrape_run_raw(result: MetalltorgScrapeResult) -> JsonObject:
    return {
        "start_url": result.start_url,
        "pages_seen": result.pages_seen,
        "products_seen": result.products_seen,
        "products_parsed": len(result.products),
        "priced_products": result.priced_products,
        "total_count": result.total_count,
        "completeness": result.completeness,
        "stop_reason": result.stop_reason,
        "failures": result.failures,
        "next_pages_seen": result.next_pages_seen,
    }


def _fetch_html(url: str, timeout: float) -> str:
    response = httpx.get(url, follow_redirects=True, timeout=timeout)
    response.raise_for_status()
    return response.text


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


def _positive_float(value: object, *, default: float) -> float:
    if not isinstance(value, int | float):
        return default
    if value <= 0:
        return default
    return float(value)
