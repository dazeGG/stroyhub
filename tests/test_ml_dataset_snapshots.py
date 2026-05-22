from datetime import UTC, datetime

from stroyhub.ml.datasets import CategoryVerifierDatasetStore
from stroyhub.ml.labels import CategoryLabelRecord, CategoryLabelStore


def test_dataset_store_creates_next_snapshot_from_live_labels(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    label_store.append(_record(product_id=1, selected_category_ids=(10,)))
    label_store.append(_record(product_id=2, selected_category_ids=()))
    store = CategoryVerifierDatasetStore(
        label_store=label_store,
        datasets_dir=tmp_path / "datasets",
    )

    snapshot = store.create_next_snapshot(
        created_at=datetime(2026, 5, 22, 1, 0, tzinfo=UTC)
    )

    assert snapshot.version == "v001"
    assert snapshot.dataset_path.read_text("utf-8") == label_store.path.read_text("utf-8")
    assert snapshot.metadata.version == "v001"
    assert snapshot.metadata.label_count == 2
    assert snapshot.metadata.labeled_product_count == 2
    assert snapshot.metadata.schema_version == 1
    assert snapshot.metadata.source_label_file == str(label_store.path)


def test_dataset_store_detects_latest_snapshot_and_next_version(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    store = CategoryVerifierDatasetStore(
        label_store=label_store,
        datasets_dir=tmp_path / "datasets",
    )
    store.create_next_snapshot()
    label_store.append(_record(product_id=1))
    store.create_next_snapshot()

    latest = store.latest_snapshot()

    assert latest is not None
    assert latest.version == "v002"
    assert store.latest_snapshot_version() == "v002"
    assert store.next_snapshot_version() == "v003"


def test_dataset_status_uses_live_counts_when_no_snapshot_exists(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    for product_id in range(1, 51):
        label_store.append(_record(product_id=product_id))
    store = CategoryVerifierDatasetStore(
        label_store=label_store,
        datasets_dir=tmp_path / "datasets",
    )

    status = store.status()

    assert status.latest_snapshot_version is None
    assert status.live_label_count == 50
    assert status.live_labeled_product_count == 50
    assert status.new_label_count == 50
    assert status.new_labeled_product_count == 50
    assert status.ready_for_training


def test_dataset_status_reports_new_labels_since_latest_snapshot(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    for product_id in range(1, 51):
        label_store.append(_record(product_id=product_id))
    store = CategoryVerifierDatasetStore(
        label_store=label_store,
        datasets_dir=tmp_path / "datasets",
    )
    store.create_next_snapshot()

    for product_id in range(51, 100):
        label_store.append(_record(product_id=product_id))

    status = store.status()

    assert status.latest_snapshot_version == "v001"
    assert status.snapshot_label_count == 50
    assert status.snapshot_labeled_product_count == 50
    assert status.new_label_count == 49
    assert status.new_labeled_product_count == 49
    assert not status.ready_for_training

    label_store.append(_record(product_id=100))

    assert store.status().ready_for_training


def test_dataset_status_counts_unique_labeled_products(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    label_store.append(_record(product_id=1))
    label_store.append(_record(product_id=1, selected_category_ids=(20,)))
    store = CategoryVerifierDatasetStore(
        label_store=label_store,
        datasets_dir=tmp_path / "datasets",
    )

    status = store.status()

    assert status.live_label_count == 2
    assert status.live_labeled_product_count == 1


def _record(
    *,
    product_id: int,
    selected_category_ids: tuple[int, ...] = (10,),
) -> CategoryLabelRecord:
    return CategoryLabelRecord(
        product_id=product_id,
        candidate_category_ids=(10, 20, 30),
        selected_category_ids=selected_category_ids,
        labeled_at=datetime(2026, 5, 22, 1, 0, tzinfo=UTC),
    )
