from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from stroyhub.db.repositories import ShopRepository
from stroyhub.models import Shop

DEFAULT_SCRAPE_INTERVAL_SECONDS = 24 * 60 * 60
MAX_BACKOFF_MULTIPLIER = 32


def list_due_shops(
    session: Session,
    *,
    now: datetime | None = None,
    source: str | None = None,
    limit: int | None = None,
) -> list[Shop]:
    due_at = now or datetime.now(UTC)
    return ShopRepository(session).list_due_for_scraping(now=due_at, source=source, limit=limit)


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


def mark_shop_scrape_completion(shop: Shop, *, completed_at: datetime, scrape_status: str) -> None:
    shop.last_scraped_at = completed_at
    if scrape_status == "success":
        shop.next_scrape_at = next_successful_scrape_at(
            completed_at=completed_at,
            scrape_interval=shop.scrape_interval,
        )
        shop.scrape_status = "success"
        shop.error_count = 0
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


def _positive_interval(value: int | None) -> int:
    if value is None or value < 1:
        return DEFAULT_SCRAPE_INTERVAL_SECONDS
    return value
