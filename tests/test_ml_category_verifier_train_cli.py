from datetime import UTC, datetime

from stroyhub.ml.labels import CategoryLabelRecord, CategoryLabelStore

from apps.ml.category_verifier.train_cli import main


def test_category_verifier_train_command_rejects_below_threshold_without_force(
    tmp_path,
    capsys,
) -> None:
    labels_path = tmp_path / "labels.jsonl"
    datasets_dir = tmp_path / "datasets"
    CategoryLabelStore(labels_path).append(
        CategoryLabelRecord(
            product_id=1,
            candidate_category_ids=(10, 20, 30),
            selected_category_ids=(10,),
            labeled_at=datetime(2026, 5, 22, 1, 0, tzinfo=UTC),
        )
    )

    exit_code = main(
        [
            "--labels-path",
            str(labels_path),
            "--datasets-dir",
            str(datasets_dir),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "new_labeled_products=1" in output
    assert "threshold=50" in output
    assert not (datasets_dir / "v001.jsonl").exists()
