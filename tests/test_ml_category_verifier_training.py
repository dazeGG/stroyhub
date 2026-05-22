import json
from datetime import UTC, date, datetime

import joblib
import pytest
from stroyhub.ml.datasets import (
    CategoryVerifierDatasetStatus,
    CategoryVerifierSnapshot,
    CategoryVerifierSnapshotMetadata,
)
from stroyhub.ml.evaluation import split_category_verifier_examples
from stroyhub.ml.features import (
    CategoryVerifierCategoryInput,
    CategoryVerifierProductInput,
    build_category_verifier_features,
)
from stroyhub.ml.labels import VerifierOutcome
from stroyhub.ml.training import (
    InsufficientTrainingDataError,
    require_training_ready,
    train_category_verifier_artifacts,
)
from stroyhub.ml.verifier import CategoryVerifierExample


def test_require_training_ready_rejects_below_threshold_without_force() -> None:
    status = _status(new_labeled_product_count=49, ready_for_training=False)

    with pytest.raises(InsufficientTrainingDataError):
        require_training_ready(status=status, force=False)

    require_training_ready(status=status, force=True)


def test_split_category_verifier_examples_uses_product_level_seed() -> None:
    examples = [
        _example(product_id=1, category_id=10, outcome="match"),
        _example(product_id=1, category_id=20, outcome="no_match"),
        _example(product_id=2, category_id=10, outcome="match"),
        _example(product_id=3, category_id=10, outcome="no_match"),
        _example(product_id=4, category_id=10, outcome="match"),
        _example(product_id=5, category_id=10, outcome="no_match"),
    ]

    split = split_category_verifier_examples(
        examples,
        run_date=date(2026, 5, 22),
    )

    train_product_ids = {example.product_id for example in split.train_examples}
    eval_product_ids = {example.product_id for example in split.eval_examples}
    assert train_product_ids.isdisjoint(eval_product_ids)
    assert split.metadata.strategy == "source_product_id_random_80_20"
    assert split.metadata.seed == 20260522
    assert split.metadata.train_ratio == 0.80
    assert split.metadata.eval_product_count == 1
    assert split.metadata.train_product_count == 4


def test_training_artifacts_save_model_metadata_current_and_errors(tmp_path) -> None:
    snapshot = CategoryVerifierSnapshot(
        version="v001",
        dataset_path=tmp_path / "datasets" / "v001.jsonl",
        metadata_path=tmp_path / "datasets" / "v001.meta.json",
        metadata=CategoryVerifierSnapshotMetadata(
            version="v001",
            created_at=datetime(2026, 5, 22, 1, 0, tzinfo=UTC),
            source_label_file=str(tmp_path / "labels.jsonl"),
            schema_version=1,
            label_count=6,
            labeled_product_count=3,
        ),
    )
    split = split_category_verifier_examples(
        [
            _example(product_id=1, category_id=10, outcome="match"),
            _example(product_id=1, category_id=20, outcome="no_match"),
            _example(product_id=2, category_id=10, outcome="match"),
            _example(product_id=2, category_id=20, outcome="no_match"),
            _example(product_id=3, category_id=10, outcome="match"),
            _example(product_id=3, category_id=20, outcome="no_match"),
        ],
        run_date=date(2026, 5, 22),
    )

    result = train_category_verifier_artifacts(
        model_version="v001",
        snapshot=snapshot,
        split=split,
        models_dir=tmp_path / "models",
        reports_dir=tmp_path / "reports",
        run_date=date(2026, 5, 22),
    )

    metadata = json.loads(result.metadata_path.read_text("utf-8"))
    loaded_model = joblib.load(result.model_path)
    assert result.model_path.exists()
    assert loaded_model.model_version == "v001"
    assert metadata["model_version"] == "v001"
    assert metadata["snapshot_version"] == "v001"
    assert metadata["feature_schema_version"] == "category_verifier_features/v1"
    assert metadata["thresholds"] == {"match": 0.8, "no_match": 0.35}
    assert metadata["evaluation_split"]["seed"] == 20260522
    assert metadata["metrics"]["label_count"] == len(split.eval_examples)
    assert result.error_report_path.exists()
    assert (tmp_path / "models" / "current").resolve() == result.model_dir


def _status(
    *,
    new_labeled_product_count: int,
    ready_for_training: bool,
) -> CategoryVerifierDatasetStatus:
    return CategoryVerifierDatasetStatus(
        live_label_count=new_labeled_product_count,
        live_labeled_product_count=new_labeled_product_count,
        latest_snapshot_version="v001",
        snapshot_label_count=0,
        snapshot_labeled_product_count=0,
        new_label_count=new_labeled_product_count,
        new_labeled_product_count=new_labeled_product_count,
        ready_for_training=ready_for_training,
    )


def _example(
    *,
    product_id: int,
    category_id: int,
    outcome: VerifierOutcome,
) -> CategoryVerifierExample:
    category = CategoryVerifierCategoryInput(
        id=category_id,
        slug="cement" if category_id == 10 else "tile_adhesives",
        name="Цемент" if category_id == 10 else "Плиточные клеи",
    )
    product_title = "Цемент М500" if outcome == "match" else "Клей плиточный"
    return CategoryVerifierExample(
        product_id=product_id,
        category_id=category_id,
        outcome=outcome,
        features=build_category_verifier_features(
            product=CategoryVerifierProductInput(
                source="test",
                title=product_title,
            ),
            category=category,
        ),
    )
