#!/usr/bin/env python
import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from stroyhub.db import SessionLocal
from stroyhub.db.repositories import ShopRepository, ShopUpsert


@dataclass(frozen=True, kw_only=True)
class WhitelistShop:
    branch_id: str
    name: str
    address: str


INITIAL_WHITELIST = [
    WhitelistShop(
        branch_id="7037402698889811",
        name="Металл Торг",
        address="Проспект Михаила Николаева, 1",
    ),
    WhitelistShop(
        branch_id="70000001007229923",
        name="Евролайн",
        address="Улица Курнатовского, 86",
    ),
    WhitelistShop(
        branch_id="7037402698836780",
        name="Пирамида",
        address="Переулок Космачёва, 2",
    ),
    WhitelistShop(
        branch_id="7037402698774152",
        name="Ондулин",
        address="Улица Чернышевского, 48",
    ),
    WhitelistShop(
        branch_id="7037402698745664",
        name="Интехстрой",
        address="Улица Леваневского, 3",
    ),
    WhitelistShop(
        branch_id="70000001021201334",
        name="Строительный мир",
        address="Улица Чернышевского, 105",
    ),
]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the initial 2GIS scrape whitelist.")
    parser.add_argument("--scrape-interval", type=int, default=86400)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    next_scrape_at = datetime.now(UTC)
    for shop in INITIAL_WHITELIST:
        print(
            "schedule shop: "
            f"source=2gis "
            f"branch_id={shop.branch_id} "
            f"name={shop.name} "
            f"next_scrape_at={next_scrape_at.isoformat()} "
            f"scrape_interval={args.scrape_interval}"
        )

    if args.dry_run:
        return 0

    with SessionLocal() as session:
        repository = ShopRepository(session)
        for shop in INITIAL_WHITELIST:
            existing = repository.get_by_source_id(source="2gis", source_id=shop.branch_id)
            raw = dict(existing.raw or {}) if existing is not None else {}
            raw.update({"source": "2gis", "branch_id": shop.branch_id, "whitelist": "initial"})

            repository.upsert(
                ShopUpsert(
                    source="2gis",
                    source_id=shop.branch_id,
                    name=shop.name,
                    address=shop.address,
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


if __name__ == "__main__":
    raise SystemExit(main())
