from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stroyhub.models.tables import Category, PriceSnapshot


def escape_like_pattern(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def category_descendant_ids(session: Session, starting_ids: Iterable[int]) -> set[int]:
    initial_ids = set(starting_ids)
    if not initial_ids:
        return set()

    category_rows = session.execute(select(Category.id, Category.parent_id))
    child_ids_by_parent: dict[int, list[int]] = {}
    known_ids: set[int] = set()
    for category_id, parent_id in category_rows:
        known_ids.add(category_id)
        if parent_id is not None:
            child_ids_by_parent.setdefault(parent_id, []).append(category_id)

    category_ids = {category_id for category_id in initial_ids if category_id in known_ids}
    pending = list(category_ids)
    while pending:
        category_id = pending.pop()
        for child_id in child_ids_by_parent.get(category_id, []):
            if child_id not in category_ids:
                category_ids.add(child_id)
                pending.append(child_id)

    return category_ids


def latest_price_subquery() -> Any:
    return (
        select(
            PriceSnapshot.source_product_id.label("source_product_id"),
            PriceSnapshot.price.label("latest_price"),
            PriceSnapshot.price_kind.label("latest_price_kind"),
            PriceSnapshot.currency.label("latest_currency"),
            PriceSnapshot.unit_raw.label("latest_unit_raw"),
            PriceSnapshot.source_updated_at.label("latest_source_updated_at"),
            PriceSnapshot.parsed_at.label("latest_parsed_at"),
            func.row_number()
            .over(
                partition_by=PriceSnapshot.source_product_id,
                order_by=(PriceSnapshot.parsed_at.desc(), PriceSnapshot.id.desc()),
            )
            .label("row_number"),
        )
        .subquery()
    )
