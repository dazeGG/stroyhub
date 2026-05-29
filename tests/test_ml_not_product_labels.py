from datetime import UTC, datetime

import pytest
from stroyhub.ml.not_product_labels import NotProductLabelRecord, NotProductLabelStore


def test_not_product_label_store_appends_and_reads_records(tmp_path) -> None:
    store = NotProductLabelStore(tmp_path / "human_labels.jsonl")
    labeled_at = datetime(2026, 5, 27, 5, 0, tzinfo=UTC)

    saved = store.append(
        NotProductLabelRecord(
            source_product_id=10,
            label="not_product",
            labeled_by="operator",
            labeled_at=labeled_at,
        )
    )

    assert saved.labeled_at == labeled_at
    assert store.read_records() == [saved]
    assert store.labeled_product_ids() == {10}


def test_not_product_label_store_latest_labels_use_last_record(tmp_path) -> None:
    store = NotProductLabelStore(tmp_path / "human_labels.jsonl")
    store.append(NotProductLabelRecord(source_product_id=10, label="not_product"))
    latest = store.append(NotProductLabelRecord(source_product_id=10, label="product"))

    assert store.latest_labels() == {10: latest}


def test_not_product_label_store_pop_last(tmp_path) -> None:
    store = NotProductLabelStore(tmp_path / "human_labels.jsonl")
    store.append(NotProductLabelRecord(source_product_id=10, label="not_product"))
    store.append(NotProductLabelRecord(source_product_id=11, label="product"))

    store.pop_last()

    assert [record.source_product_id for record in store.read_records()] == [10]


def test_not_product_label_store_rejects_unknown_label(tmp_path) -> None:
    store = NotProductLabelStore(tmp_path / "human_labels.jsonl")

    with pytest.raises(ValueError, match="label"):
        store.append(  # type: ignore[arg-type]
            NotProductLabelRecord(source_product_id=10, label="maybe")
        )
