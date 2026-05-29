import logging
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from sqlalchemy.orm import Session

from stroyhub.models import Shop
from stroyhub.parsers.metalltorg import METALLTORG_SOURCE
from stroyhub.parsers.unicom import UNICOM_SOURCE
from stroyhub.scraping.metalltorg import persist_metalltorg_scrape_failure, scrape_metalltorg_shop
from stroyhub.scraping.scheduler import (
    mark_shop_scrape_completion,
    mark_shop_scrape_failure,
    mark_shop_scrape_started,
)
from stroyhub.scraping.twogis import (
    TWOGIS_LARGE_CATALOG_PAGE_SIZE,
    TWOGIS_LARGE_CATALOG_THRESHOLD,
    build_twogis_large_catalog_raw,
    persist_twogis_scrape_result,
    scrape_twogis_branch,
    twogis_large_catalog_state,
    update_twogis_large_catalog_progress,
)
from stroyhub.scraping.unicom import persist_unicom_scrape_failure, scrape_unicom_shop

logger = logging.getLogger(__name__)

SUPPORTED_SCHEDULED_SOURCES = frozenset({"2gis", METALLTORG_SOURCE, UNICOM_SOURCE})
SUPPORTED_SCHEDULED_SOURCE_TYPES = frozenset({"2gis", "official_api", "official_html"})


def run_shop_scrape(session: Session, shop_id: int) -> dict[str, Any]:
    task_started_at = monotonic()
    shop = session.get(Shop, shop_id)
    if shop is None:
        logger.error("shop not found for scraping", extra={"shop_id": shop_id})
        return {"shop_id": shop_id, "status": "failed", "error": "shop_not_found"}

    if shop.scrape_status == "disabled":
        logger.info(
            "shop source disabled; skipping scrape",
            extra={"shop_id": shop.id, "source": shop.source, "source_type": shop.source_type},
        )
        return {
            "shop_id": shop.id,
            "source": shop.source,
            "source_type": shop.source_type,
            "status": "skipped",
            "reason": "source_disabled",
        }

    if shop.scrape_status == "running":
        logger.info(
            "shop source already running; skipping duplicate scrape",
            extra={"shop_id": shop.id, "source": shop.source, "source_type": shop.source_type},
        )
        return {
            "shop_id": shop.id,
            "source": shop.source,
            "source_type": shop.source_type,
            "status": "skipped",
            "reason": "scrape_already_running",
        }

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
        mark_shop_scrape_started(shop, started_at=completed_at)
        session.commit()
        if shop.source == "2gis":
            large_state = twogis_large_catalog_state(shop.raw)
            if large_state is None or not large_state.enabled:
                probe = scrape_twogis_branch(
                    branch_id=shop.source_id,
                    page_size=TWOGIS_LARGE_CATALOG_PAGE_SIZE,
                    max_pages=1,
                )
                if (
                    probe.total is not None
                    and probe.total > TWOGIS_LARGE_CATALOG_THRESHOLD
                ):
                    raw = dict(shop.raw or {})
                    raw["twogis_large_catalog"] = build_twogis_large_catalog_raw(
                        enabled=False,
                        total=probe.total,
                        next_page=1,
                        items_loaded=0,
                        completed=False,
                        last_stop_reason="large_catalog_requires_operator_enable",
                    )
                    shop.raw = raw
                    shop.scrape_status = "disabled"
                    session.commit()
                    return {
                        "shop_id": shop.id,
                        "source": shop.source,
                        "source_type": shop.source_type,
                        "status": "skipped",
                        "reason": "large_catalog_requires_operator_enable",
                        "total": probe.total,
                    }

            large_state = twogis_large_catalog_state(shop.raw)
            if large_state is not None and large_state.enabled:
                result = scrape_twogis_branch(
                    branch_id=shop.source_id,
                    start_page=large_state.next_page,
                    page_size=large_state.page_size,
                    max_pages=large_state.pages_per_run,
                )
                persisted_twogis = persist_twogis_scrape_result(
                    session,
                    result,
                    shop_name=shop.name,
                    finished_at=completed_at,
                    partial_shop_status="partial",
                    require_patron_model=True,
                )
                refreshed_shop = session.get(Shop, shop.id)
                if refreshed_shop is not None:
                    refreshed_shop.raw = update_twogis_large_catalog_progress(
                        refreshed_shop.raw,
                        result,
                    )
                scrape_status = persisted_twogis.scrape_status
                products_seen = result.items_seen
                products_saved = persisted_twogis.source_products_saved
                price_snapshots_saved = persisted_twogis.price_snapshots_saved
                partial_progress = scrape_status == "partial"
            else:
                result = scrape_twogis_branch(branch_id=shop.source_id)
                persisted_twogis = persist_twogis_scrape_result(
                    session,
                    result,
                    shop_name=shop.name,
                    finished_at=completed_at,
                    require_patron_model=True,
                )
                scrape_status = persisted_twogis.scrape_status
                products_seen = result.items_seen
                products_saved = persisted_twogis.source_products_saved
                price_snapshots_saved = persisted_twogis.price_snapshots_saved
                partial_progress = False
        elif shop.source == UNICOM_SOURCE:
            persisted_unicom = scrape_unicom_shop(
                session,
                shop,
                finished_at=completed_at,
                require_patron_model=True,
            )
            scrape_status = persisted_unicom.scrape_status
            products_seen = persisted_unicom.products_seen
            products_saved = persisted_unicom.source_products_saved
            price_snapshots_saved = persisted_unicom.price_snapshots_saved
            partial_progress = (
                scrape_status == "partial" and persisted_unicom.batch_progress
            )
        else:
            persisted_metalltorg = scrape_metalltorg_shop(
                session,
                shop,
                finished_at=completed_at,
                require_patron_model=True,
            )
            scrape_status = persisted_metalltorg.scrape_status
            products_seen = persisted_metalltorg.products_seen
            products_saved = persisted_metalltorg.source_products_saved
            price_snapshots_saved = persisted_metalltorg.price_snapshots_saved
            partial_progress = False

        mark_shop_scrape_completion(
            shop,
            completed_at=completed_at,
            scrape_status=scrape_status,
            partial_is_progress=partial_progress,
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
            if source == METALLTORG_SOURCE:
                persist_metalltorg_scrape_failure(
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
            "source_type": shop.source_type,
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
        "source_type": shop.source_type,
        "status": scrape_status,
        "duration_seconds": round(duration_seconds, 3),
        "products_seen": products_seen,
        "products_saved": products_saved,
        "price_snapshots_saved": price_snapshots_saved,
    }
