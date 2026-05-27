from datetime import UTC, datetime

from stroyhub.ml.labels import CategoryLabelRecord, CategoryLabelStore

from apps.ml.category_verifier.dataset_cli import main


def test_category_verifier_dataset_command_prints_status(tmp_path, capsys) -> None:
    labels_path = tmp_path / "labels.jsonl"
    datasets_dir = tmp_path / "datasets"
    store = CategoryLabelStore(labels_path)
    store.append(_record(product_id=1))

    exit_code = main(
        [
            "--labels-path",
            str(labels_path),
            "--datasets-dir",
            str(datasets_dir),
            "status",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "live_labels=1" in output
    assert "latest_snapshot=none" in output
    assert "new_labeled_products=1" in output
    assert "ready_for_training=false" in output


def test_category_verifier_dataset_command_creates_snapshot(tmp_path, capsys) -> None:
    labels_path = tmp_path / "labels.jsonl"
    datasets_dir = tmp_path / "datasets"
    store = CategoryLabelStore(labels_path)
    store.append(_record(product_id=1))

    exit_code = main(
        [
            "--labels-path",
            str(labels_path),
            "--datasets-dir",
            str(datasets_dir),
            "snapshot",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "snapshot=v001" in output
    assert "label_count=1" in output
    assert (datasets_dir / "v001.jsonl").exists()
    assert (datasets_dir / "v001.meta.json").exists()


def _record(*, product_id: int) -> CategoryLabelRecord:
    return CategoryLabelRecord(
        product_id=product_id,
        candidate_category_ids=(10, 20, 30),
        selected_category_ids=(10,),
        labeled_at=datetime(2026, 5, 22, 1, 0, tzinfo=UTC),
    )
