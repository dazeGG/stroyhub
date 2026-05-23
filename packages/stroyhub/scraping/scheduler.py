from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from stroyhub.db.repositories import ShopRepository
from stroyhub.models import Shop

DEFAULT_SCRAPE_INTERVAL_SECONDS = 24 * 60 * 60
BATCH_PROGRESS_INTERVAL_SECONDS = 15 * 60
LARGE_SOURCE_PRODUCT_THRESHOLD = 5_000
LARGE_SOURCE_SCRAPE_INTERVAL_SECONDS = 7 * 24 * 60 * 60
MAX_BACKOFF_MULTIPLIER = 32


def list_due_shops(
    session: Session,
    *,
    now: datetime | None = None,
    source: str | None = None,
    source_type: str | None = None,
    limit: int | None = None,
) -> list[Shop]:
    due_at = now or datetime.now(UTC)
    return ShopRepository(session).list_due_for_scraping(
        now=due_at,
        source=source,
        source_type=source_type,
        limit=limit,
    )


def next_successful_scrape_at(
    *,
    completed_at: datetime,
    scrape_interval: int | None,
) -> datetime:
    interval = _positive_interval(scrape_interval)
    return completed_at + timedelta(seconds=interval)


def next_failed_scrape_at(
    *,
    failed_at: datetime,
    scrape_interval: int | None,
    error_count: int,
) -> datetime:
    interval = _positive_interval(scrape_interval)
    multiplier = min(2 ** max(error_count - 1, 0), MAX_BACKOFF_MULTIPLIER)
    return failed_at + timedelta(seconds=interval * multiplier)


def mark_shop_scrape_completion(
    shop: Shop,
    *,
    completed_at: datetime,
    scrape_status: str,
    partial_is_progress: bool = False,
) -> None:
    shop.last_scraped_at = completed_at
    if scrape_status == "success":
        if _large_source_product_total(shop.raw) > LARGE_SOURCE_PRODUCT_THRESHOLD:
            shop.next_scrape_at = completed_at + timedelta(
                seconds=LARGE_SOURCE_SCRAPE_INTERVAL_SECONDS
            )
        else:
            shop.next_scrape_at = next_successful_scrape_at(
                completed_at=completed_at,
                scrape_interval=shop.scrape_interval,
            )
        shop.scrape_status = "success"
        shop.error_count = 0
        return

    if scrape_status == "partial" and partial_is_progress:
        shop.next_scrape_at = completed_at + timedelta(
            seconds=BATCH_PROGRESS_INTERVAL_SECONDS
        )
        shop.scrape_status = "partial"
        return

    shop.error_count += 1
    shop.next_scrape_at = next_failed_scrape_at(
        failed_at=completed_at,
        scrape_interval=shop.scrape_interval,
        error_count=shop.error_count,
    )
    shop.scrape_status = "failed"


def mark_shop_scrape_failure(shop: Shop, *, failed_at: datetime, error: str) -> None:
    shop.last_scraped_at = failed_at
    shop.error_count += 1
    shop.next_scrape_at = next_failed_scrape_at(
        failed_at=failed_at,
        scrape_interval=shop.scrape_interval,
        error_count=shop.error_count,
    )
    shop.scrape_status = "failed"

    raw = dict(shop.raw or {})
    raw["last_scrape_error"] = error
    shop.raw = raw


def mark_shop_scrape_started(shop: Shop, *, started_at: datetime) -> None:
    shop.scrape_status = "running"
    raw = dict(shop.raw or {})
    raw["last_scrape_started_at"] = started_at.isoformat()
    raw.pop("last_scrape_error", None)
    shop.raw = raw


def _positive_interval(value: int | None) -> int:
    if value is None or value < 1:
        return DEFAULT_SCRAPE_INTERVAL_SECONDS
    return value


def _large_source_product_total(raw: object) -> int:
    if not isinstance(raw, dict):
        return 0

    twogis_state = raw.get("twogis_large_catalog")
    twogis_total = twogis_state.get("total") if isinstance(twogis_state, dict) else None
    if isinstance(twogis_total, int):
        return twogis_total

    unicom_state = raw.get("unicom_category_batch")
    if isinstance(unicom_state, dict):
        total_products = unicom_state.get("total_products")
        if isinstance(total_products, int):
            return total_products

    return 0
