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
from stroyhub.parsers.metalltorg import METALLTORG_SHOP_SOURCE_ID, METALLTORG_SOURCE
from stroyhub.scraping.metalltorg import (
    METALLTORG_DEFAULT_CATEGORY_URLS,
    METALLTORG_DEFAULT_MAX_PAGES,
    METALLTORG_DEFAULT_SHOP_NAME,
    METALLTORG_DEFAULT_SHOP_URL,
    METALLTORG_DEFAULT_TIMEOUT,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the official Metalltorg HTML source.")
    parser.add_argument("--scrape-interval", type=int, default=86400)
    parser.add_argument("--category-url", action="append", dest="category_urls")
    parser.add_argument("--max-pages", type=int, default=METALLTORG_DEFAULT_MAX_PAGES)
    parser.add_argument("--timeout", type=float, default=METALLTORG_DEFAULT_TIMEOUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    category_urls = tuple(args.category_urls or METALLTORG_DEFAULT_CATEGORY_URLS)
    next_scrape_at = datetime.now(UTC)
    print(
        "schedule shop: "
        f"source={METALLTORG_SOURCE} "
        f"source_type=official_html "
        f"shop_source_id={METALLTORG_SHOP_SOURCE_ID} "
        f"name={METALLTORG_DEFAULT_SHOP_NAME} "
        f"category_urls={len(category_urls)} "
        f"max_pages={args.max_pages} "
        f"timeout={args.timeout} "
        f"next_scrape_at={next_scrape_at.isoformat()} "
        f"scrape_interval={args.scrape_interval}"
    )

    if args.dry_run:
        return 0

    with SessionLocal() as session:
        identity = _get_or_create_metalltorg_identity(session)
        repository = ShopRepository(session)
        existing = repository.get_by_source_id(
            source=METALLTORG_SOURCE,
            source_id=METALLTORG_SHOP_SOURCE_ID,
        )
        raw = dict(existing.raw or {}) if existing is not None else {}
        raw.update(
            {
                "source": METALLTORG_SOURCE,
                "source_type": "official_html",
                "category_urls": list(category_urls),
                "max_pages": args.max_pages,
                "timeout": args.timeout,
                "pacing": "sequential pages and categories; no concurrent requests",
                "selector_health": "brittle_html",
            }
        )

        repository.upsert(
            ShopUpsert(
                source=METALLTORG_SOURCE,
                source_id=METALLTORG_SHOP_SOURCE_ID,
                source_type="official_html",
                shop_identity_id=identity.id,
                name=METALLTORG_DEFAULT_SHOP_NAME,
                url=METALLTORG_DEFAULT_SHOP_URL,
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


def _get_or_create_metalltorg_identity(session) -> ShopIdentity:  # type: ignore[no-untyped-def]
    identity = session.scalar(
        select(ShopIdentity).where(ShopIdentity.preferred_source == METALLTORG_SOURCE).limit(1)
    )
    if identity is not None:
        return identity

    return ShopIdentityRepository(session).create(
        ShopIdentityCreate(
            display_name=METALLTORG_DEFAULT_SHOP_NAME,
            website_url=METALLTORG_DEFAULT_SHOP_URL,
            preferred_source=METALLTORG_SOURCE,
            locked_fields={"display_name": True, "website_url": True},
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
