#!/usr/bin/env python
import argparse
from collections.abc import Sequence

from stroyhub.catalog.taxonomy import DEFAULT_NORMALIZED_CATEGORIES
from stroyhub.db import SessionLocal
from stroyhub.db.repositories import CategoryRepository, CategoryUpsert


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the normalized StroyHub category tree.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    for category in DEFAULT_NORMALIZED_CATEGORIES:
        parent_hint = f" parent={category.parent_slug}" if category.parent_slug else ""
        print(f"seed category: slug={category.slug}{parent_hint} name={category.name}")

    if args.dry_run:
        return 0

    with SessionLocal() as session:
        repository = CategoryRepository(session)
        category_ids: dict[str, int] = {}

        for category in DEFAULT_NORMALIZED_CATEGORIES:
            parent_id = category_ids.get(category.parent_slug) if category.parent_slug else None
            stored = repository.upsert(
                CategoryUpsert(
                    slug=category.slug,
                    name=category.name,
                    parent_id=parent_id,
                )
            )
            category_ids[category.slug] = stored.id

        session.commit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
