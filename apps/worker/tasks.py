import logging
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from stroyhub.db import SessionLocal
from stroyhub.models import Shop
from stroyhub.parsers.unicom import UNICOM_SOURCE
from stroyhub.scraping import (
    persist_twogis_scrape_result,
    persist_unicom_scrape_failure,
    scrape_twogis_branch,
    scrape_unicom_shop,
)
from stroyhub.scraping.scheduler import (
    list_due_shops,
    mark_shop_scrape_completion,
    mark_shop_scrape_failure,
)

from apps.worker.celery_app import celery_app

logger = logging.getLogger(__name__)
SUPPORTED_SCHEDULED_SOURCES = frozenset({"2gis", UNICOM_SOURCE})


@celery_app.task(name="stroyhub.scrape_due_shops")  # type: ignore[untyped-decorator]
def scrape_due_shops(*, limit: int | None = None) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    with SessionLocal() as session:
        shops = [
            shop
            for shop in list_due_shops(session, now=started_at, limit=limit)
            if shop.source in SUPPORTED_SCHEDULED_SOURCES
        ]
        shop_ids = [shop.id for shop in shops]

        for shop_id in shop_ids:
            scrape_shop.delay(shop_id)

    logger.info("scheduled due shops", extra={"shop_count": len(shop_ids), "shop_ids": shop_ids})
    return {"scheduled": len(shop_ids), "shop_ids": shop_ids}


@celery_app.task(name="stroyhub.scrape_shop")  # type: ignore[untyped-decorator]
def scrape_shop(shop_id: int) -> dict[str, Any]:
    task_started_at = monotonic()
    with SessionLocal() as session:
        shop = session.get(Shop, shop_id)
        if shop is None:
            logger.error("shop not found for scraping", extra={"shop_id": shop_id})
            return {"shop_id": shop_id, "status": "failed", "error": "shop_not_found"}

        if shop.source not in SUPPORTED_SCHEDULED_SOURCES:
            error = f"unsupported source: {shop.source}"
            failed_at = datetime.now(UTC)
            mark_shop_scrape_failure(shop, failed_at=failed_at, error=error)
            session.commit()
            logger.error(
                "unsupported shop source for scraping",
                extra={"shop_id": shop.id, "source": shop.source, "error": error},
            )
            return {"shop_id": shop.id, "source": shop.source, "status": "failed", "error": error}

        try:
            completed_at = datetime.now(UTC)
            if shop.source == "2gis":
                result = scrape_twogis_branch(branch_id=shop.source_id)
                persisted_twogis = persist_twogis_scrape_result(
                    session,
                    result,
                    shop_name=shop.name,
                    finished_at=completed_at,
                )
                scrape_status = persisted_twogis.scrape_status
                products_seen = result.items_seen
                products_saved = persisted_twogis.source_products_saved
                price_snapshots_saved = persisted_twogis.price_snapshots_saved
            else:
                persisted_unicom = scrape_unicom_shop(
                    session,
                    shop,
                    finished_at=completed_at,
                )
                scrape_status = persisted_unicom.scrape_status
                products_seen = persisted_unicom.products_seen
                products_saved = persisted_unicom.source_products_saved
                price_snapshots_saved = persisted_unicom.price_snapshots_saved

            mark_shop_scrape_completion(
                shop,
                completed_at=completed_at,
                scrape_status=scrape_status,
            )
            session.commit()
        except Exception as exc:
            source = shop.source
            failed_at = datetime.now(UTC)
            error = str(exc)
            session.rollback()
            failed_shop = session.get(Shop, shop_id)
            if failed_shop is not None:
                if source == UNICOM_SOURCE:
                    persist_unicom_scrape_failure(
                        session,
                        failed_shop,
                        error=error,
                        failed_at=failed_at,
                    )
                mark_shop_scrape_failure(failed_shop, failed_at=failed_at, error=error)
                session.commit()
            duration_seconds = monotonic() - task_started_at
            logger.exception(
                "scrape shop failed",
                extra={
                    "shop_id": shop_id,
                    "source": source,
                    "duration_seconds": round(duration_seconds, 3),
                    "error": error,
                },
            )
            raise

    duration_seconds = monotonic() - task_started_at
    logger.info(
        "scrape shop finished",
        extra={
            "shop_id": shop.id,
            "source": shop.source,
            "duration_seconds": round(duration_seconds, 3),
            "products_seen": products_seen,
            "products_saved": products_saved,
            "price_snapshots_saved": price_snapshots_saved,
            "scrape_status": scrape_status,
        },
    )
    return {
        "shop_id": shop.id,
        "source": shop.source,
        "status": scrape_status,
        "duration_seconds": round(duration_seconds, 3),
        "products_seen": products_seen,
        "products_saved": products_saved,
        "price_snapshots_saved": price_snapshots_saved,
    }
