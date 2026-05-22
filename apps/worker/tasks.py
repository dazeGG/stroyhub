import logging
from datetime import UTC, datetime
from typing import Any

from stroyhub.db import SessionLocal
from stroyhub.scraping.runner import (
    SUPPORTED_SCHEDULED_SOURCE_TYPES,
    SUPPORTED_SCHEDULED_SOURCES,
    run_shop_scrape,
)
from stroyhub.scraping.scheduler import (
    list_due_shops,
)

from apps.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="stroyhub.scrape_due_shops")  # type: ignore[untyped-decorator]
def scrape_due_shops(
    *,
    source: str | None = None,
    source_type: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    if source_type is not None and source_type not in SUPPORTED_SCHEDULED_SOURCE_TYPES:
        raise ValueError(f"unsupported source_type: {source_type}")

    started_at = datetime.now(UTC)
    with SessionLocal() as session:
        due_shops = list_due_shops(
            session,
            now=started_at,
            source=source,
            source_type=source_type,
            limit=limit,
        )
        shops = [shop for shop in due_shops if shop.source in SUPPORTED_SCHEDULED_SOURCES]
        shop_ids = [shop.id for shop in shops]
        skipped_unsupported_shop_ids = [
            shop.id for shop in due_shops if shop.source not in SUPPORTED_SCHEDULED_SOURCES
        ]

        for shop_id in shop_ids:
            scrape_shop.delay(shop_id)

    logger.info(
        "scheduled due shops",
        extra={
            "shop_count": len(shop_ids),
            "shop_ids": shop_ids,
            "source": source,
            "source_type": source_type,
            "skipped_unsupported_shop_ids": skipped_unsupported_shop_ids,
        },
    )
    return {
        "scheduled": len(shop_ids),
        "shop_ids": shop_ids,
        "source": source,
        "source_type": source_type,
        "skipped_unsupported_shop_ids": skipped_unsupported_shop_ids,
    }


@celery_app.task(name="stroyhub.scrape_shop")  # type: ignore[untyped-decorator]
def scrape_shop(shop_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        return run_shop_scrape(session, shop_id)
