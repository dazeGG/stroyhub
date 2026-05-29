from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from stroyhub.catalog.products import format_price_text
from stroyhub.catalog.query_helpers import latest_price_subquery
from stroyhub.ml.not_product_classifier import PATRON_MODEL_NAME
from stroyhub.ml.not_product_labels import (
    NotProductLabel,
    NotProductLabelRecord,
    NotProductLabelStore,
)
from stroyhub.models import Category, OperatorDecision, Shop, SourceProduct

PATRON_DATASET_SCHEMA_VERSION = 3
PATRON_LABEL_POLICY_VERSION = "catalog_suitability_v1"
PATRON_DB_POLICY_LABEL_PRIORITY = 10
PATRON_BULK_LABEL_PRIORITY = 70
PATRON_HUMAN_LABEL_PRIORITY = 100
PATRON_REVIEW_LABEL_PRIORITY = 100

_REVIEW_LABEL_ACTIONS: dict[str, NotProductLabel] = {
    "patron_review_product": "product",
    "patron_review_not_product": "not_product",
}
_REVIEW_ACTIONS = frozenset(
    {
        "patron_review_product",
        "patron_review_not_product",
        "patron_review_skip",
    }
)


@dataclass(frozen=True, kw_only=True)
class PatronLabelCandidate:
    source_product_id: int
    label: NotProductLabel
    label_source: str
    label_priority: int
    label_recorded_at: datetime
    label_reasons: tuple[str, ...] = ()
    actor: str | None = None
    reason: str | None = None
    decision_hash: str | None = None


@dataclass(frozen=True, kw_only=True)
class PatronDatasetBuildResult:
    dataset_path: Path
    manifest_path: Path
    record_count: int
    label_counts: dict[str, int]
    label_source_counts: dict[str, int]
    label_priority_counts: dict[str, int]
    review_label_count: int


def build_patron_dataset_snapshot(
    *,
    session: Session,
    dataset_path: Path,
    model_version: str,
    manifest_path: Path | None = None,
    bulk_labels_path: Path | None = None,
    human_labels_path: Path | None = None,
    include_inactive: bool = False,
    source_product_ids: Iterable[int] | None = None,
    limit: int | None = None,
    created_at: datetime | None = None,
) -> PatronDatasetBuildResult:
    created_at = _aware_datetime(created_at or datetime.now(UTC))
    manifest_path = manifest_path or dataset_path.with_name("dataset_manifest.json")
    source_product_id_set = (
        {int(product_id) for product_id in source_product_ids}
        if source_product_ids is not None
        else None
    )

    bulk_labels = _label_store_candidates(
        bulk_labels_path,
        label_source="patron_bulk_labels",
        label_priority=PATRON_BULK_LABEL_PRIORITY,
    )
    human_labels = _label_store_candidates(
        human_labels_path,
        label_source="patron_cli_human_labels",
        label_priority=PATRON_HUMAN_LABEL_PRIORITY,
    )
    review_labels = patron_review_label_candidates(session)
    categories_by_id = _categories_by_id(session)

    rows: list[dict[str, Any]] = []
    for product_row in _source_product_rows(
        session,
        include_inactive=include_inactive,
        source_product_ids=source_product_id_set,
        limit=limit,
    ):
        product = product_row.product
        label = _best_label(
            _db_policy_label(product, price_kind=product_row.latest_price_kind),
            bulk_labels.get(product.id),
            human_labels.get(product.id),
            review_labels.get(product.id),
        )
        rows.append(
            _dataset_record(
                product_row,
                category_path=_category_path(product_row.category, categories_by_id),
                label=label,
                model_version=model_version,
            )
        )

    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(dataset_path, rows)
    manifest = _manifest(
        rows,
        dataset_path=dataset_path,
        model_version=model_version,
        created_at=created_at,
        review_label_count=sum(
            1 for row in rows if row.get("label_source") == "operator_patron_review"
        ),
        include_inactive=include_inactive,
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return PatronDatasetBuildResult(
        dataset_path=dataset_path,
        manifest_path=manifest_path,
        record_count=len(rows),
        label_counts=dict(Counter(str(row["label"]) for row in rows)),
        label_source_counts=dict(Counter(str(row["label_source"]) for row in rows)),
        label_priority_counts=dict(
            Counter(str(row["label_priority"]) for row in rows)
        ),
        review_label_count=manifest["review_label_count"],
    )


def patron_review_label_candidates(
    session: Session,
) -> dict[int, PatronLabelCandidate]:
    undone_decision_ids = _undone_review_decision_ids(session)
    latest_by_product: dict[int, PatronLabelCandidate] = {}
    statement = (
        select(OperatorDecision)
        .where(
            OperatorDecision.decision_type == "data_quality",
            OperatorDecision.action.in_(_REVIEW_ACTIONS),
            OperatorDecision.source_product_id.is_not(None),
        )
        .order_by(OperatorDecision.decided_at.asc(), OperatorDecision.id.asc())
    )
    for decision in session.scalars(statement):
        if decision.id in undone_decision_ids or decision.source_product_id is None:
            continue
        if decision.action == "patron_review_skip":
            latest_by_product.pop(decision.source_product_id, None)
            continue
        label = _REVIEW_LABEL_ACTIONS.get(decision.action)
        if label is None:
            continue
        latest_by_product[decision.source_product_id] = PatronLabelCandidate(
            source_product_id=decision.source_product_id,
            label=label,
            label_source="operator_patron_review",
            label_priority=PATRON_REVIEW_LABEL_PRIORITY,
            label_recorded_at=_aware_datetime(decision.decided_at),
            label_reasons=(decision.action,),
            actor=decision.actor,
            reason=decision.reason,
            decision_hash=_decision_hash(decision),
        )
    return latest_by_product


@dataclass(frozen=True, kw_only=True)
class _SourceProductRow:
    product: SourceProduct
    shop: Shop
    category: Category | None
    latest_price: Decimal | None
    latest_price_kind: str | None
    latest_currency: str | None
    latest_unit_raw: str | None
    latest_source_updated_at: datetime | None
    latest_parsed_at: datetime | None


def _source_product_rows(
    session: Session,
    *,
    include_inactive: bool,
    source_product_ids: set[int] | None,
    limit: int | None,
) -> list[_SourceProductRow]:
    latest_prices = latest_price_subquery()
    statement = (
        select(
            SourceProduct,
            Shop,
            Category,
            latest_prices.c.latest_price,
            latest_prices.c.latest_price_kind,
            latest_prices.c.latest_currency,
            latest_prices.c.latest_unit_raw,
            latest_prices.c.latest_source_updated_at,
            latest_prices.c.latest_parsed_at,
        )
        .join(Shop, Shop.id == SourceProduct.shop_id)
        .outerjoin(Category, Category.id == SourceProduct.category_id)
        .outerjoin(
            latest_prices,
            and_(
                latest_prices.c.source_product_id == SourceProduct.id,
                latest_prices.c.row_number == 1,
            ),
        )
        .order_by(SourceProduct.id.asc())
    )
    if not include_inactive:
        statement = statement.where(SourceProduct.is_active.is_(True))
    if source_product_ids is not None:
        statement = statement.where(SourceProduct.id.in_(source_product_ids))
    if limit is not None:
        statement = statement.limit(limit)

    return [
        _SourceProductRow(
            product=product,
            shop=shop,
            category=category,
            latest_price=latest_price,
            latest_price_kind=latest_price_kind,
            latest_currency=latest_currency,
            latest_unit_raw=latest_unit_raw,
            latest_source_updated_at=latest_source_updated_at,
            latest_parsed_at=latest_parsed_at,
        )
        for (
            product,
            shop,
            category,
            latest_price,
            latest_price_kind,
            latest_currency,
            latest_unit_raw,
            latest_source_updated_at,
            latest_parsed_at,
        ) in session.execute(statement)
    ]


def _label_store_candidates(
    path: Path | None,
    *,
    label_source: str,
    label_priority: int,
) -> dict[int, PatronLabelCandidate]:
    if path is None or not path.exists():
        return {}
    candidates: dict[int, PatronLabelCandidate] = {}
    for record in NotProductLabelStore.from_path(path).latest_labels().values():
        candidates[record.source_product_id] = _label_store_candidate(
            record,
            label_source=label_source,
            label_priority=label_priority,
        )
    return candidates


def _label_store_candidate(
    record: NotProductLabelRecord,
    *,
    label_source: str,
    label_priority: int,
) -> PatronLabelCandidate:
    return PatronLabelCandidate(
        source_product_id=record.source_product_id,
        label=record.label,
        label_source=label_source,
        label_priority=label_priority,
        label_recorded_at=_aware_datetime(record.labeled_at),
        label_reasons=(label_source,),
        actor=record.labeled_by,
    )


def _db_policy_label(
    product: SourceProduct,
    *,
    price_kind: str | None,
) -> PatronLabelCandidate:
    label: NotProductLabel = "not_product" if product.is_not_product else "product"
    reasons: list[str] = []
    if product.is_not_product:
        reasons.append("db_is_not_product")
    if price_kind in {"from", "range", "unknown"}:
        reasons.append("non_exact_price")
    return PatronLabelCandidate(
        source_product_id=product.id,
        label=label,
        label_source="stroyhub_patron_policy",
        label_priority=PATRON_DB_POLICY_LABEL_PRIORITY,
        label_recorded_at=_aware_datetime(product.last_seen_at),
        label_reasons=tuple(reasons),
    )


def _best_label(*candidates: PatronLabelCandidate | None) -> PatronLabelCandidate:
    available = [candidate for candidate in candidates if candidate is not None]
    if not available:
        raise ValueError("at least one Patron label candidate is required")
    return max(
        available,
        key=lambda candidate: (
            candidate.label_priority,
            candidate.label_recorded_at,
            candidate.label_source,
        ),
    )


def _dataset_record(
    row: _SourceProductRow,
    *,
    category_path: tuple[Category, ...],
    label: PatronLabelCandidate,
    model_version: str,
) -> dict[str, Any]:
    product = row.product
    latest_price = _latest_price_payload(row)
    record = _compact(
        {
            "schema_version": PATRON_DATASET_SCHEMA_VERSION,
            "task": "patron",
            "model_name": PATRON_MODEL_NAME,
            "dataset_version": model_version,
            "source": product.source,
            "shop": _shop_payload(row.shop),
            "product": _product_payload(product, row.category, category_path),
            "latest_price": latest_price,
            "label": label.label,
            "label_source": label.label_source,
            "label_priority": label.label_priority,
            "label_policy_version": PATRON_LABEL_POLICY_VERSION,
            "label_reasons": list(label.label_reasons),
            "label_recorded_at": _isoformat(label.label_recorded_at),
            "label_review": _review_payload(label),
        }
    )
    record["example_hash"] = _record_hash(record)
    return record


def _shop_payload(shop: Shop) -> dict[str, Any]:
    return _compact(
        {
            "name": shop.name,
            "address": shop.address,
            "url": shop.url,
        }
    )


def _product_payload(
    product: SourceProduct,
    category: Category | None,
    category_path: tuple[Category, ...],
) -> dict[str, Any]:
    return _compact(
        {
            "title": product.title,
            "normalized_title": product.normalized_title,
            "description": product.description,
            "category_raw": product.category_raw,
            "category_name": category.name if category is not None else None,
            "category_path": [category.name for category in category_path],
            "unit_raw": product.unit_raw,
            "image_url": product.image_url,
            "source_updated_at": _optional_isoformat(product.source_updated_at),
            "first_seen_at": _isoformat(product.first_seen_at),
            "last_seen_at": _isoformat(product.last_seen_at),
            "is_active": product.is_active,
        }
    )


def _latest_price_payload(row: _SourceProductRow) -> dict[str, Any]:
    price_kind = row.latest_price_kind or "unknown"
    currency = row.latest_currency or "RUB"
    return _compact(
        {
            "price": _decimal_text(row.latest_price),
            "price_kind": price_kind,
            "price_text": format_price_text(
                price=row.latest_price,
                currency=currency,
                price_kind=price_kind,
            ),
            "currency": currency,
            "unit_raw": row.latest_unit_raw,
            "source_updated_at": _optional_isoformat(row.latest_source_updated_at),
            "parsed_at": _optional_isoformat(row.latest_parsed_at),
        }
    )


def _review_payload(label: PatronLabelCandidate) -> dict[str, Any] | None:
    if label.label_source != "operator_patron_review":
        return None
    return _compact(
        {
            "decision_hash": label.decision_hash,
            "actor": label.actor,
            "reason": label.reason,
        }
    )


def _manifest(
    rows: list[dict[str, Any]],
    *,
    dataset_path: Path,
    model_version: str,
    created_at: datetime,
    review_label_count: int,
    include_inactive: bool,
) -> dict[str, Any]:
    label_counts = Counter(str(row["label"]) for row in rows)
    source_counts = Counter(str(row["source"]) for row in rows)
    label_source_counts = Counter(str(row["label_source"]) for row in rows)
    label_priority_counts = Counter(str(row["label_priority"]) for row in rows)
    source_label_counts = Counter(
        f"{row['source']}:{row['label']}" for row in rows
    )
    latest_price_kind_counts = Counter(
        str(row.get("latest_price", {}).get("price_kind") or "unknown")
        for row in rows
    )
    return {
        "schema_version": PATRON_DATASET_SCHEMA_VERSION,
        "task": "patron",
        "label_policy_version": PATRON_LABEL_POLICY_VERSION,
        "dataset_path": str(dataset_path),
        "created_at": _isoformat(created_at),
        "record_count": len(rows),
        "label_counts": dict(label_counts),
        "source_counts": dict(source_counts),
        "source_label_counts": dict(source_label_counts),
        "label_source_counts": dict(label_source_counts),
        "label_priority_counts": dict(label_priority_counts),
        "latest_price_kind_counts": dict(latest_price_kind_counts),
        "review_label_count": review_label_count,
        "contains_database_ids": False,
        "contains_source_product_ids": False,
        "include_inactive": include_inactive,
        "identity_policy": (
            "Records intentionally omit DB ids, source product ids, shop ids, "
            "category ids, fingerprints, and raw source payloads. Operator review "
            "rows carry a one-way decision_hash for traceability without storing "
            "operator_decisions.id."
        ),
        "ordering": "Rows are exported in source_products.id ASC order, but ids are not stored.",
        "model_name": PATRON_MODEL_NAME,
        "model_version": model_version,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            file.write("\n")


def _categories_by_id(session: Session) -> dict[int, Category]:
    return {category.id: category for category in session.scalars(select(Category))}


def _category_path(
    category: Category | None,
    categories_by_id: dict[int, Category],
) -> tuple[Category, ...]:
    if category is None:
        return ()
    path: list[Category] = []
    current: Category | None = category
    seen_ids: set[int] = set()
    while current is not None and current.id not in seen_ids:
        path.append(current)
        seen_ids.add(current.id)
        current = categories_by_id.get(current.parent_id or 0)
    return tuple(reversed(path))


def _undone_review_decision_ids(session: Session) -> set[int]:
    statement = select(OperatorDecision.evidence).where(
        OperatorDecision.decision_type == "data_quality",
        OperatorDecision.action == "patron_review_undo",
    )
    undone_ids: set[int] = set()
    for evidence in session.scalars(statement):
        if not isinstance(evidence, dict):
            continue
        value = evidence.get("undone_decision_id")
        if isinstance(value, int):
            undone_ids.add(value)
        elif isinstance(value, str) and value.isdecimal():
            undone_ids.add(int(value))
    return undone_ids


def _decision_hash(decision: OperatorDecision) -> str:
    decided_at = _isoformat(_aware_datetime(decision.decided_at))
    raw = f"{decision.id}:{decision.source_product_id}:{decision.action}:{decided_at}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _record_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("example_hash", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _optional_isoformat(value: datetime | None) -> str | None:
    return _isoformat(value) if value is not None else None


def _isoformat(value: datetime) -> str:
    return _aware_datetime(value).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _aware_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
