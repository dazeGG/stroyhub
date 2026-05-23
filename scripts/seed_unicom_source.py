#!/usr/bin/env python
import argparse
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from stroyhub.db import (
    SessionLocal,
    ShopIdentityCreate,
    ShopIdentityRepository,
    ShopRepository,
    ShopUpsert,
)
from stroyhub.models import ShopIdentity
from stroyhub.parsers.unicom import UNICOM_DEFAULT_SHOP_SOURCE_ID, UNICOM_SOURCE, UnicomClient
from stroyhub.scraping.unicom import (
    UNICOM_DEFAULT_CATEGORIES_PER_RUN,
    UNICOM_DEFAULT_CATEGORY_UUIDS,
    UNICOM_DEFAULT_LIMIT,
    UNICOM_DEFAULT_MAX_PAGES,
    UNICOM_DEFAULT_SHOP_NAME,
    UNICOM_DEFAULT_SHOP_URL,
    UNICOM_DEFAULT_SORT,
    build_unicom_category_batch_raw,
)

UNICOM_DEFAULT_SCRAPE_INTERVAL = 7 * 24 * 60 * 60


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the official Unicom catalog source.")
    parser.add_argument("--scrape-interval", type=int, default=UNICOM_DEFAULT_SCRAPE_INTERVAL)
    parser.add_argument("--category-uuid", action="append", dest="category_uuids")
    parser.add_argument(
        "--discover-categories",
        action="store_true",
        help="Fetch Unicom catalog menu and seed all leaf category UUIDs.",
    )
    parser.add_argument("--categories-per-run", type=int, default=UNICOM_DEFAULT_CATEGORIES_PER_RUN)
    parser.add_argument("--limit", type=int, default=UNICOM_DEFAULT_LIMIT)
    parser.add_argument("--max-pages", type=int, default=UNICOM_DEFAULT_MAX_PAGES)
    parser.add_argument("--sort", default=UNICOM_DEFAULT_SORT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    category_uuids = _category_uuids(
        explicit=args.category_uuids,
        discover=args.discover_categories,
    )
    next_scrape_at = datetime.now(UTC)
    print(
        "schedule shop: "
        f"source={UNICOM_SOURCE} "
        f"source_type=official_api "
        f"shop_source_id={UNICOM_DEFAULT_SHOP_SOURCE_ID} "
        f"name={UNICOM_DEFAULT_SHOP_NAME} "
        f"category_uuids={len(category_uuids)} "
        f"categories_per_run={args.categories_per_run} "
        f"limit={args.limit} "
        f"max_pages={args.max_pages} "
        f"sort={args.sort} "
        f"next_scrape_at={next_scrape_at.isoformat()} "
        f"scrape_interval={args.scrape_interval}"
    )

    if args.dry_run:
        return 0

    with SessionLocal() as session:
        identity = _get_or_create_unicom_identity(session)
        repository = ShopRepository(session)
        existing = repository.get_by_source_id(
            source=UNICOM_SOURCE,
            source_id=UNICOM_DEFAULT_SHOP_SOURCE_ID,
        )
        raw = dict(existing.raw or {}) if existing is not None else {}
        raw.update(
            {
                "source": UNICOM_SOURCE,
                "source_type": "official_api",
                "category_uuids": list(category_uuids),
                "category_discovery": (
                    "catalog_menu_leaf_categories"
                    if args.discover_categories
                    else "explicit_or_default"
                ),
                "categories_per_run": args.categories_per_run,
                "limit": args.limit,
                "max_pages": args.max_pages,
                "sort": args.sort,
                "pacing": "sequential categories; no concurrent requests",
                "unicom_category_batch": build_unicom_category_batch_raw(
                    enabled=len(category_uuids) > args.categories_per_run,
                    total=len(category_uuids),
                    categories_per_run=args.categories_per_run,
                ),
            }
        )

        repository.upsert(
            ShopUpsert(
                source=UNICOM_SOURCE,
                source_id=UNICOM_DEFAULT_SHOP_SOURCE_ID,
                source_type="official_api",
                shop_identity_id=identity.id,
                name=UNICOM_DEFAULT_SHOP_NAME,
                url=UNICOM_DEFAULT_SHOP_URL,
                last_scraped_at=existing.last_scraped_at if existing is not None else None,
                next_scrape_at=(
                    existing.next_scrape_at
                    if existing is not None and existing.next_scrape_at is not None
                    else next_scrape_at
                ),
                scrape_interval=args.scrape_interval,
                scrape_status=existing.scrape_status if existing is not None else "scheduled",
                error_count=existing.error_count if existing is not None else None,
                raw=raw,
            )
        )
        session.commit()

    return 0


def _category_uuids(
    *,
    explicit: list[str] | None,
    discover: bool,
) -> tuple[str, ...]:
    if explicit:
        return tuple(explicit)
    if discover:
        discovered = UnicomClient().fetch_leaf_category_uuids()
        return discovered or UNICOM_DEFAULT_CATEGORY_UUIDS
    return UNICOM_DEFAULT_CATEGORY_UUIDS


def _get_or_create_unicom_identity(session) -> ShopIdentity:  # type: ignore[no-untyped-def]
    identity = session.scalar(
        select(ShopIdentity)
        .where(ShopIdentity.display_name == UNICOM_DEFAULT_SHOP_NAME)
        .order_by(ShopIdentity.id.asc())
        .limit(1)
    )
    if identity is not None:
        identity.preferred_source = UNICOM_SOURCE
        identity.website_url = identity.website_url or UNICOM_DEFAULT_SHOP_URL
        locked_fields = dict(identity.locked_fields or {})
        locked_fields.update({"display_name": True, "website_url": True})
        identity.locked_fields = locked_fields
        session.flush()
        return identity

    identity = session.scalar(
        select(ShopIdentity).where(ShopIdentity.preferred_source == UNICOM_SOURCE).limit(1)
    )
    if identity is not None:
        return identity

    return ShopIdentityRepository(session).create(
        ShopIdentityCreate(
            display_name=UNICOM_DEFAULT_SHOP_NAME,
            website_url=UNICOM_DEFAULT_SHOP_URL,
            preferred_source=UNICOM_SOURCE,
            locked_fields={"display_name": True, "website_url": True},
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
