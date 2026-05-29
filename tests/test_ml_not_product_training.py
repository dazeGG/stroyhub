import json
from datetime import date

import joblib
from stroyhub.core.config import settings
from stroyhub.ml.not_product_classifier import (
    LinearNotProductClassifierModel,
    NotProductClassifierModelUnavailableError,
    NotProductExample,
    NotProductPrediction,
    PatronClassifier,
    build_not_product_text,
    load_not_product_examples,
    train_not_product_classifier_baseline,
)
from stroyhub.ml.not_product_labels import NotProductLabel
from stroyhub.ml.not_product_training import (
    split_not_product_examples,
    train_not_product_classifier_artifacts,
)

from apps.ml.patron.train_cli import main as train_main
from scripts.check_patron_readiness import main as readiness_main


def test_not_product_model_predicts_generic_product_title_as_not_product(tmp_path) -> None:
    dataset_path = tmp_path / "dataset.jsonl"
    _write_dataset(dataset_path)
    examples = load_not_product_examples(dataset_path)

    model = train_not_product_classifier_baseline(
        model_version="v-test",
        examples=examples,
        threshold=0.5,
    )

    product_prediction = model.predict("цемент м500 50кг цемент")
    not_product_prediction = model.predict("Товар")

    assert product_prediction.label == "product"
    assert not_product_prediction.label == "not_product"


def test_split_not_product_examples_is_stratified(tmp_path) -> None:
    dataset_path = tmp_path / "dataset.jsonl"
    _write_dataset(dataset_path)
    examples = load_not_product_examples(dataset_path)

    split = split_not_product_examples(
        examples,
        run_date=date(2026, 5, 27),
    )

    assert split.metadata.strategy == "stratified_label_group_random_80_20"
    assert split.metadata.seed == 20260527
    assert split.metadata.train_label_counts == {"not_product": 4, "product": 8}
    assert split.metadata.eval_label_counts == {"not_product": 1, "product": 2}


def test_split_not_product_examples_keeps_groups_in_one_side() -> None:
    examples = [
        *_grouped_examples("product", "product-a"),
        *_grouped_examples("product", "product-b"),
        *_grouped_examples("product", "product-c"),
        *_grouped_examples("product", "product-d"),
        *_grouped_examples("not_product", "not-product-a"),
        *_grouped_examples("not_product", "not-product-b"),
        *_grouped_examples("not_product", "not-product-c"),
        *_grouped_examples("not_product", "not-product-d"),
    ]

    split = split_not_product_examples(
        examples,
        run_date=date(2026, 5, 27),
    )

    train_groups = {example.group_key for example in split.train_examples}
    eval_groups = {example.group_key for example in split.eval_examples}
    assert split.eval_examples
    assert train_groups.isdisjoint(eval_groups)


def test_not_product_model_applies_non_exact_price_rule(tmp_path) -> None:
    dataset_path = tmp_path / "dataset.jsonl"
    _write_dataset(dataset_path)
    examples = load_not_product_examples(dataset_path)
    model = train_not_product_classifier_baseline(
        model_version="v-test",
        examples=examples,
    )

    text = build_not_product_text(
        {
            "source": "2gis",
            "product": {
                "title": "Брус от 100х100 мм до 180х180 мм",
                "normalized_title": "брус от 100х100 мм до 180х180 мм",
            },
            "latest_price": {
                "price": "29000.00",
                "price_kind": "from",
            },
        }
    )

    prediction = model.predict(text)

    assert prediction.label == "not_product"
    assert prediction.not_product_probability == 1.0


def test_train_not_product_classifier_artifacts_save_model_metadata_current_and_errors(
    tmp_path,
) -> None:
    model_dir = tmp_path / "models" / "v0"
    dataset_path = model_dir / "dataset.jsonl"
    model_dir.mkdir(parents=True)
    _write_dataset(dataset_path)

    result = train_not_product_classifier_artifacts(
        dataset_path=dataset_path,
        model_dir=model_dir,
        model_version="v0",
        run_date=date(2026, 5, 27),
    )

    metadata = json.loads(result.metadata_path.read_text("utf-8"))
    loaded_model = joblib.load(result.model_path)
    assert isinstance(loaded_model, LinearNotProductClassifierModel)
    assert loaded_model.model_version == "v0"
    assert metadata["model_name"] == "Patron"
    assert metadata["model_version"] == "v0"
    assert metadata["model_type"] == "tfidf_sgd_logistic_regression"
    assert metadata["training_model_type"] == "linear"
    assert metadata["feature_schema_version"] == "patron_features/v3"
    assert metadata["thresholds"] == {"not_product": 0.7}
    assert metadata["score_normalization"] == "l2_normalized_tfidf_logistic_score"
    assert metadata["training_split"]["eval_label_counts"] == {
        "not_product": 1,
        "product": 2,
    }
    assert result.error_report_path.exists()
    assert (tmp_path / "models" / "current").resolve() == result.model_dir


def test_patron_classifier_loads_artifact_and_predicts_record(tmp_path) -> None:
    model_dir = tmp_path / "models" / "v0"
    dataset_path = model_dir / "dataset.jsonl"
    model_dir.mkdir(parents=True)
    _write_dataset(dataset_path)
    train_not_product_classifier_artifacts(
        dataset_path=dataset_path,
        model_dir=model_dir,
        model_version="v0",
        run_date=date(2026, 5, 27),
    )

    classifier = PatronClassifier.load(model_dir)
    prediction = classifier.predict_record(
        {
            "source": "2gis",
            "product": {
                "title": "Товар",
                "normalized_title": "товар",
                "category_raw": "Розетки",
                "category_name": "Розетки",
            },
            "latest_price": {
                "price": None,
                "price_kind": "unknown",
            },
        }
    )

    assert prediction.label == "not_product"
    assert prediction.model_name == "Patron"
    assert prediction.model_version == "v0"
    assert prediction.feature_schema_version == "patron_features/v3"
    assert prediction.threshold == 0.7


def test_patron_classifier_applies_metadata_threshold_to_prediction_label() -> None:
    classifier = PatronClassifier(
        model=_FixedProbabilityModel(not_product_probability=0.6),
        metadata={"thresholds": {"not_product": 0.7}},
    )

    prediction = classifier.predict_record({"product": {"title": "Товар"}})

    assert prediction.label == "product"
    assert prediction.not_product_probability == 0.6
    assert prediction.confidence == 0.4
    assert prediction.threshold == 0.7


def test_patron_classifier_default_can_use_explicit_model_dir(tmp_path) -> None:
    model_dir = tmp_path / "custom" / "patron-current"
    dataset_path = model_dir / "dataset.jsonl"
    model_dir.mkdir(parents=True)
    _write_dataset(dataset_path)
    train_not_product_classifier_artifacts(
        dataset_path=dataset_path,
        model_dir=model_dir,
        model_version="v0",
        run_date=date(2026, 5, 27),
    )

    classifier = PatronClassifier.default(model_dir=model_dir)

    assert classifier.model_version == "v0"
    assert PatronClassifier.default_model_dir(model_dir=model_dir) == model_dir


def test_patron_classifier_reports_missing_artifact(tmp_path) -> None:
    try:
        PatronClassifier.load(tmp_path / "missing")
    except NotProductClassifierModelUnavailableError as error:
        assert "Patron model is unavailable" in str(error)
    else:
        raise AssertionError("expected missing Patron model error")


def test_patron_readiness_cli_checks_model_without_database(
    tmp_path, capsys, monkeypatch
) -> None:
    model_dir = tmp_path / "models" / "v0"
    dataset_path = model_dir / "dataset.jsonl"
    model_dir.mkdir(parents=True)
    _write_dataset(dataset_path)
    train_not_product_classifier_artifacts(
        dataset_path=dataset_path,
        model_dir=model_dir,
        model_version="v0",
        run_date=date(2026, 5, 27),
    )

    monkeypatch.setattr(settings, "patron_model_dir", str(model_dir))

    exit_code = readiness_main(["--skip-db"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "model_loaded=true" in output
    assert "patron_ready=true" in output


def test_patron_train_cli_trains_from_dataset(tmp_path, capsys) -> None:
    model_dir = tmp_path / "models" / "v0"
    dataset_path = model_dir / "dataset.jsonl"
    model_dir.mkdir(parents=True)
    _write_dataset(dataset_path)

    exit_code = train_main(
        [
            "--model-dir",
            str(model_dir),
            "--run-date",
            "2026-05-27",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "model_version=v0" in output
    assert "train_labels=12" in output
    assert "eval_labels=3" in output
    assert "not_product_f1=" in output
    assert (model_dir / "model.joblib").exists()
    assert (model_dir / "metadata.json").exists()


def _write_dataset(path) -> None:
    rows = [
        *_examples("product", 10, "Цемент М500 50кг", "Цемент", "cement"),
        *_examples("not_product", 5, "Товар", "Розетки", "generic"),
    ]
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False))
            file.write("\n")


def _examples(label: str, count: int, title: str, category: str, prefix: str) -> list[dict]:
    return [
        {
            "example_hash": f"{prefix}-{index}",
            "schema_version": 1,
            "task": "patron",
            "source": "test",
            "shop": {"name": "Test Shop"},
            "product": {
                "title": f"{title} {index}" if label == "product" else title,
                "normalized_title": f"{title} {index}" if label == "product" else title,
                "category_raw": category,
                "category_name": category,
                "category_path": [category],
                "unit_raw": "шт",
            },
            "latest_price": {
                "currency": "RUB",
                "unit_raw": "шт",
                "price_kind": "exact",
            },
            "label": label,
            "label_source": "test",
        }
        for index in range(count)
    ]


def _grouped_examples(label: NotProductLabel, group_key: str) -> list[NotProductExample]:
    return [
        NotProductExample(
            example_hash=f"{group_key}-{index}",
            label=label,
            text=f"{group_key} {index}",
            title=f"{group_key} {index}",
            source="test",
            group_key=group_key,
        )
        for index in range(2)
    ]


class _FixedProbabilityModel:
    model_version = "v-test"
    threshold = 0.5

    def __init__(self, *, not_product_probability: float) -> None:
        self._not_product_probability = not_product_probability

    def predict(self, _text: str) -> NotProductPrediction:
        return NotProductPrediction(
            label="not_product",
            not_product_probability=self._not_product_probability,
            confidence=self._not_product_probability,
        )
