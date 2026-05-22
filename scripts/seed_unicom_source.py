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
from stroyhub.parsers.unicom import UNICOM_DEFAULT_SHOP_SOURCE_ID, UNICOM_SOURCE
from stroyhub.scraping.unicom import (
    UNICOM_DEFAULT_CATEGORY_UUIDS,
    UNICOM_DEFAULT_LIMIT,
    UNICOM_DEFAULT_MAX_PAGES,
    UNICOM_DEFAULT_SHOP_NAME,
    UNICOM_DEFAULT_SHOP_URL,
    UNICOM_DEFAULT_SORT,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the official Unicom catalog source.")
    parser.add_argument("--scrape-interval", type=int, default=86400)
    parser.add_argument("--category-uuid", action="append", dest="category_uuids")
    parser.add_argument("--limit", type=int, default=UNICOM_DEFAULT_LIMIT)
    parser.add_argument("--max-pages", type=int, default=UNICOM_DEFAULT_MAX_PAGES)
    parser.add_argument("--sort", default=UNICOM_DEFAULT_SORT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    category_uuids = tuple(args.category_uuids or UNICOM_DEFAULT_CATEGORY_UUIDS)
    next_scrape_at = datetime.now(UTC)
    print(
        "schedule shop: "
        f"source={UNICOM_SOURCE} "
        f"source_type=official_api "
        f"shop_source_id={UNICOM_DEFAULT_SHOP_SOURCE_ID} "
        f"name={UNICOM_DEFAULT_SHOP_NAME} "
        f"category_uuids={len(category_uuids)} "
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
                "limit": args.limit,
                "max_pages": args.max_pages,
                "sort": args.sort,
                "pacing": "sequential categories; no concurrent requests",
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


def _get_or_create_unicom_identity(session) -> ShopIdentity:  # type: ignore[no-untyped-def]
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
