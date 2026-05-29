import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import (
    OperatorDecisionCreate,
    OperatorDecisionRepository,
    PriceSnapshotCreate,
    PriceSnapshotRepository,
    ShopRepository,
    ShopUpsert,
    SourceProductRepository,
    SourceProductUpsert,
)
from stroyhub.ml.not_product_labels import NotProductLabelRecord, NotProductLabelStore
from stroyhub.ml.patron_dataset import build_patron_dataset_snapshot
from stroyhub.models import Category, OperatorDecision, SourceProduct


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 1})

    try:
        connection = engine.connect()
    except OperationalError:
        engine.dispose()
        pytest.skip("PostgreSQL is not available")

    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_patron_dataset_uses_admin_review_label_with_top_priority(
    db_session: Session,
    tmp_path: Path,
) -> None:
    product = _source_product(db_session, source_id="patron-dataset-review")
    bulk_labels_path = tmp_path / "labels.jsonl"
    NotProductLabelStore(bulk_labels_path).append(
        NotProductLabelRecord(
            source_product_id=product.id,
            label="product",
            labeled_by="codex-chat",
            labeled_at=datetime(2026, 5, 27, 10, 0, tzinfo=UTC),
        )
    )
    _review_decision(
        db_session,
        product,
        action="patron_review_not_product",
        decided_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
    )

    result = build_patron_dataset_snapshot(
        session=db_session,
        dataset_path=tmp_path / "dataset.jsonl",
        manifest_path=tmp_path / "dataset_manifest.json",
        model_version="v3",
        bulk_labels_path=bulk_labels_path,
        human_labels_path=tmp_path / "missing-human-labels.jsonl",
        source_product_ids=[product.id],
        created_at=datetime(2026, 5, 28, 11, 0, tzinfo=UTC),
    )

    rows = _read_jsonl(result.dataset_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["label"] == "not_product"
    assert row["label_source"] == "operator_patron_review"
    assert row["label_priority"] == 100
    assert row["label_reasons"] == ["patron_review_not_product"]
    assert row["label_review"]["actor"] == "reviewer"
    assert "decision_hash" in row["label_review"]
    assert "source_product_id" not in row
    assert "source_product_id" not in row["product"]
    assert row["latest_price"]["price_text"] == "1200.00 RUB"
    assert row["example_hash"]

    manifest = json.loads(result.manifest_path.read_text("utf-8"))
    assert manifest["record_count"] == 1
    assert manifest["review_label_count"] == 1
    assert manifest["contains_database_ids"] is False
    assert manifest["contains_source_product_ids"] is False


def test_patron_dataset_ignores_undone_review_decisions(
    db_session: Session,
    tmp_path: Path,
) -> None:
    product = _source_product(db_session, source_id="patron-dataset-undo")
    decision = _review_decision(
        db_session,
        product,
        action="patron_review_not_product",
        decided_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
    )
    OperatorDecisionRepository(db_session).create(
        OperatorDecisionCreate(
            decision_type="data_quality",
            action="patron_review_undo",
            entity_type="source_product",
            entity_id=product.id,
            source_product_id=product.id,
            evidence={"undone_decision_id": decision.id},
            decided_at=datetime(2026, 5, 28, 10, 1, tzinfo=UTC),
        )
    )

    result = build_patron_dataset_snapshot(
        session=db_session,
        dataset_path=tmp_path / "dataset.jsonl",
        model_version="v3",
        source_product_ids=[product.id],
        created_at=datetime(2026, 5, 28, 11, 0, tzinfo=UTC),
    )

    row = _read_jsonl(result.dataset_path)[0]
    assert row["label"] == "product"
    assert row["label_source"] == "stroyhub_patron_policy"
    assert row["label_priority"] == 10
    assert "label_review" not in row


def test_patron_dataset_human_labels_override_bulk_labels(
    db_session: Session,
    tmp_path: Path,
) -> None:
    product = _source_product(db_session, source_id="patron-dataset-human")
    bulk_labels_path = tmp_path / "labels.jsonl"
    human_labels_path = tmp_path / "human_labels.jsonl"
    NotProductLabelStore(bulk_labels_path).append(
        NotProductLabelRecord(
            source_product_id=product.id,
            label="product",
            labeled_by="codex-chat",
            labeled_at=datetime(2026, 5, 27, 10, 0, tzinfo=UTC),
        )
    )
    NotProductLabelStore(human_labels_path).append(
        NotProductLabelRecord(
            source_product_id=product.id,
            label="not_product",
            labeled_by="operator",
            labeled_at=datetime(2026, 5, 27, 10, 5, tzinfo=UTC),
        )
    )

    result = build_patron_dataset_snapshot(
        session=db_session,
        dataset_path=tmp_path / "dataset.jsonl",
        model_version="v3",
        bulk_labels_path=bulk_labels_path,
        human_labels_path=human_labels_path,
        source_product_ids=[product.id],
        created_at=datetime(2026, 5, 28, 11, 0, tzinfo=UTC),
    )

    row = _read_jsonl(result.dataset_path)[0]
    assert row["label"] == "not_product"
    assert row["label_source"] == "patron_cli_human_labels"
    assert row["label_priority"] == 100


def test_patron_dataset_skips_unreviewed_patron_needs_review_rows(
    db_session: Session,
    tmp_path: Path,
) -> None:
    product = _source_product(
        db_session,
        source_id="patron-dataset-needs-review",
        raw={
            "catalog_eligibility": {
                "status": "needs_review",
                "method": "patron",
                "reasons": ["patron_uncertain"],
            }
        },
    )

    result = build_patron_dataset_snapshot(
        session=db_session,
        dataset_path=tmp_path / "dataset.jsonl",
        model_version="v3",
        source_product_ids=[product.id],
        created_at=datetime(2026, 5, 28, 11, 0, tzinfo=UTC),
    )

    assert _read_jsonl(result.dataset_path) == []
    assert result.record_count == 0
    assert result.source_product_count == 1
    assert result.skipped_counts == {"needs_review": 1}


def test_patron_dataset_labels_2gis_non_exact_price_policy_as_not_product(
    db_session: Session,
    tmp_path: Path,
) -> None:
    product = _source_product(
        db_session,
        source_id="patron-dataset-from-price",
        price_kind="from",
    )

    result = build_patron_dataset_snapshot(
        session=db_session,
        dataset_path=tmp_path / "dataset.jsonl",
        model_version="v3",
        source_product_ids=[product.id],
        created_at=datetime(2026, 5, 28, 11, 0, tzinfo=UTC),
    )

    row = _read_jsonl(result.dataset_path)[0]
    assert row["label"] == "not_product"
    assert row["label_source"] == "stroyhub_patron_policy"
    assert "non_exact_price" in row["label_reasons"]


def test_patron_dataset_skips_unreviewed_patron_auto_rejects(
    db_session: Session,
    tmp_path: Path,
) -> None:
    product = _source_product(
        db_session,
        source_id="patron-dataset-auto-reject",
        raw={
            "catalog_eligibility": {
                "status": "ineligible",
                "method": "patron",
                "reasons": ["patron_not_product"],
            }
        },
        is_not_product=True,
    )

    result = build_patron_dataset_snapshot(
        session=db_session,
        dataset_path=tmp_path / "dataset.jsonl",
        model_version="v3",
        source_product_ids=[product.id],
        created_at=datetime(2026, 5, 28, 11, 0, tzinfo=UTC),
    )

    assert _read_jsonl(result.dataset_path) == []
    assert result.skipped_counts == {"patron_auto_label": 1}


def test_patron_dataset_uses_operator_data_problem_label_with_top_priority(
    db_session: Session,
    tmp_path: Path,
) -> None:
    product = _source_product(
        db_session,
        source_id="patron-dataset-data-problem",
        raw={
            "catalog_eligibility": {
                "status": "ineligible",
                "method": "patron",
                "reasons": ["patron_not_product"],
            },
            "operator_review": {
                "data_problem": {
                    "marked": False,
                    "actor": "reviewer",
                    "reason": "specific source card",
                    "reviewed_at": "2026-05-28T10:30:00Z",
                }
            },
        },
        is_not_product=True,
    )

    result = build_patron_dataset_snapshot(
        session=db_session,
        dataset_path=tmp_path / "dataset.jsonl",
        model_version="v3",
        source_product_ids=[product.id],
        created_at=datetime(2026, 5, 28, 11, 0, tzinfo=UTC),
    )

    row = _read_jsonl(result.dataset_path)[0]
    assert row["label"] == "product"
    assert row["label_source"] == "operator_data_problem"
    assert row["label_priority"] == 100
    assert row["label_review"]["actor"] == "reviewer"


def test_patron_dataset_example_hash_is_stable_across_relabels(
    db_session: Session,
    tmp_path: Path,
) -> None:
    product = _source_product(db_session, source_id="patron-dataset-stable-hash")
    product_path = tmp_path / "dataset-product.jsonl"
    not_product_path = tmp_path / "dataset-not-product.jsonl"
    product_labels_path = tmp_path / "product-labels.jsonl"
    not_product_labels_path = tmp_path / "not-product-labels.jsonl"
    NotProductLabelStore(product_labels_path).append(
        NotProductLabelRecord(source_product_id=product.id, label="product")
    )
    NotProductLabelStore(not_product_labels_path).append(
        NotProductLabelRecord(source_product_id=product.id, label="not_product")
    )

    product_result = build_patron_dataset_snapshot(
        session=db_session,
        dataset_path=product_path,
        model_version="v3",
        bulk_labels_path=product_labels_path,
        source_product_ids=[product.id],
        created_at=datetime(2026, 5, 28, 11, 0, tzinfo=UTC),
    )
    not_product_result = build_patron_dataset_snapshot(
        session=db_session,
        dataset_path=not_product_path,
        model_version="v3",
        bulk_labels_path=not_product_labels_path,
        source_product_ids=[product.id],
        created_at=datetime(2026, 5, 28, 11, 5, tzinfo=UTC),
    )

    product_row = _read_jsonl(product_result.dataset_path)[0]
    not_product_row = _read_jsonl(not_product_result.dataset_path)[0]
    assert product_row["label"] == "product"
    assert not_product_row["label"] == "not_product"
    assert product_row["example_hash"] == not_product_row["example_hash"]


def test_patron_dataset_example_hash_is_stable_across_observation_timestamps(
    db_session: Session,
    tmp_path: Path,
) -> None:
    product = _source_product(db_session, source_id="patron-dataset-stable-time-hash")
    first_path = tmp_path / "dataset-first.jsonl"
    second_path = tmp_path / "dataset-second.jsonl"

    first_result = build_patron_dataset_snapshot(
        session=db_session,
        dataset_path=first_path,
        model_version="v3",
        source_product_ids=[product.id],
        created_at=datetime(2026, 5, 28, 11, 0, tzinfo=UTC),
    )
    product.last_seen_at = datetime(2026, 5, 29, 9, 0, tzinfo=UTC)
    product.source_updated_at = datetime(2026, 5, 29, 8, 55, tzinfo=UTC)
    PriceSnapshotRepository(db_session).add(
        PriceSnapshotCreate(
            source_product_id=product.id,
            price=Decimal("1200.00"),
            price_kind="exact",
            parsed_at=datetime(2026, 5, 29, 9, 1, tzinfo=UTC),
            source_updated_at=datetime(2026, 5, 29, 8, 55, tzinfo=UTC),
        )
    )

    second_result = build_patron_dataset_snapshot(
        session=db_session,
        dataset_path=second_path,
        model_version="v3",
        source_product_ids=[product.id],
        created_at=datetime(2026, 5, 29, 11, 0, tzinfo=UTC),
    )

    first_row = _read_jsonl(first_result.dataset_path)[0]
    second_row = _read_jsonl(second_result.dataset_path)[0]
    assert first_row["example_hash"] == second_row["example_hash"]


def _source_product(
    session: Session,
    *,
    source_id: str,
    raw: dict[str, object] | None = None,
    is_not_product: bool = False,
    price: Decimal | None = Decimal("1200.00"),
    price_kind: str = "exact",
) -> SourceProduct:
    raw = raw or {"catalog_eligibility": {"status": "eligible", "method": "rules"}}
    category = Category(slug=f"{source_id}-category", name="Patron Dataset Category")
    session.add(category)
    session.flush()
    shop = ShopRepository(session).upsert(
        ShopUpsert(
            source="2gis",
            source_id=f"shop-{source_id}",
            name="Patron Dataset Shop",
            address="Dataset Street",
            url="https://example.test/shop",
        )
    )
    product = SourceProductRepository(session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id=source_id,
            title="Patron Dataset Cement 25kg",
            normalized_title="patron dataset cement 25kg",
            category_id=category.id,
            category_raw="Цемент",
            unit_raw="мешок",
            raw=raw,
            observed_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
            is_not_product=is_not_product,
        )
    )
    PriceSnapshotRepository(session).add(
        PriceSnapshotCreate(
            source_product_id=product.id,
            price=price,
            price_kind=price_kind,
            parsed_at=datetime(2026, 5, 28, 9, 1, tzinfo=UTC),
        )
    )
    return product


def _review_decision(
    session: Session,
    product: SourceProduct,
    *,
    action: str,
    decided_at: datetime,
) -> OperatorDecision:
    return OperatorDecisionRepository(session).create(
        OperatorDecisionCreate(
            decision_type="data_quality",
            action=action,
            entity_type="source_product",
            entity_id=product.id,
            source_product_id=product.id,
            actor="reviewer",
            reason="admin Patron review",
            decided_at=decided_at,
        )
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
    ]
