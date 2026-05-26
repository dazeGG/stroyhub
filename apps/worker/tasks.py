import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session
from stroyhub.catalog.quality_pipeline import CatalogQualityPipeline
from stroyhub.catalog.shop_candidates import CandidateListFilters, ShopCandidateCatalog
from stroyhub.db import SessionLocal
from stroyhub.models import Shop
from stroyhub.parsers.twogis import TwogisClient
from stroyhub.scraping.runner import (
    SUPPORTED_SCHEDULED_SOURCE_TYPES,
    SUPPORTED_SCHEDULED_SOURCES,
    run_shop_scrape,
)
from stroyhub.scraping.scheduler import list_due_shops
from stroyhub.scraping.twogis import (
    TWOGIS_LARGE_CATALOG_PAGE_SIZE,
    build_twogis_large_catalog_raw,
    twogis_large_catalog_state,
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
        result = run_shop_scrape(session, shop_id)

    should_enqueue_quality = (
        result.get("status") in {"success", "partial"}
        and int(result.get("products_saved") or 0) > 0
    )
    if should_enqueue_quality:
        run_catalog_quality_pipeline.delay(shop_id)
    if result.get("status") in {"success", "partial"}:
        result["catalog_quality_pipeline_scheduled"] = should_enqueue_quality
    return result


@celery_app.task(name="stroyhub.run_catalog_quality_pipeline")  # type: ignore[untyped-decorator]
def run_catalog_quality_pipeline(shop_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        result = CatalogQualityPipeline(session).run_for_shop(shop_id)
        session.commit()
        return result.as_raw()


@celery_app.task(name="stroyhub.refresh_shop_source_candidates")  # type: ignore[untyped-decorator]
def refresh_shop_source_candidates_task() -> dict[str, Any]:
    with SessionLocal() as session:
        catalog = ShopCandidateCatalog(session)
        summary = catalog.refresh_from_twogis()
        session.commit()
        items = catalog.list_candidates(CandidateListFilters())
        return {
            "checked": summary.checked,
            "created": summary.created,
            "updated": summary.updated,
            "stale": summary.stale,
            "skipped_approved": summary.skipped_approved,
            "items": len(items),
        }


@celery_app.task(name="stroyhub.verify_shop_source_candidate_twogis_data")  # type: ignore[untyped-decorator]
def verify_shop_source_candidate_twogis_data_task(candidate_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        catalog = ShopCandidateCatalog(session)
        candidate, verification = catalog.verify_twogis_data(candidate_id)
        session.commit()
        return {
            "candidate_id": candidate.id,
            "website_found": verification.website_found,
            "products_found": verification.products_found,
            "website_url": verification.website_url,
            "product_count": verification.product_count,
            "priced_product_count": verification.priced_product_count,
        }


@celery_app.task(name="stroyhub.enable_twogis_large_catalog")  # type: ignore[untyped-decorator]
def enable_twogis_large_catalog_task(shop_id: int) -> dict[str, Any]:
    with SessionLocal() as session:
        shop = _get_twogis_shop_or_fail(shop_id, session)
        page = TwogisClient().fetch_branch_page(
            branch_id=shop.source_id,
            page=1,
            page_size=TWOGIS_LARGE_CATALOG_PAGE_SIZE,
        )
        existing_state = twogis_large_catalog_state(shop.raw)
        raw = dict(shop.raw or {})
        prior_items_seen = raw.get("items_seen")
        inferred_next_page = (
            int(prior_items_seen) // TWOGIS_LARGE_CATALOG_PAGE_SIZE + 1
            if isinstance(prior_items_seen, int) and prior_items_seen > 0
            else 1
        )
        raw["twogis_large_catalog"] = build_twogis_large_catalog_raw(
            enabled=True,
            total=page.total,
            next_page=(
                existing_state.next_page if existing_state is not None else inferred_next_page
            ),
            items_loaded=(
                existing_state.items_loaded
                if existing_state is not None
                else max(inferred_next_page - 1, 0) * TWOGIS_LARGE_CATALOG_PAGE_SIZE
            ),
            completed=False,
            last_stop_reason="operator_enabled",
        )
        shop.raw = raw
        shop.scrape_status = "scheduled"
        session.commit()
        return {"shop_id": shop.id, "status": "scheduled", "total": page.total}


def _get_twogis_shop_or_fail(shop_id: int, session: Session) -> Shop:
    shop = session.get(Shop, shop_id)
    if shop is None:
        raise ValueError("shop not found")
    if shop.source != "2gis":
        raise ValueError("large catalog mode is only for 2GIS shops")
    return shop
