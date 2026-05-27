import json
from datetime import date

import joblib
from stroyhub.ml.not_product_classifier import (
    NotProductClassifierModel,
    build_not_product_text,
    load_not_product_examples,
    train_not_product_classifier_baseline,
)
from stroyhub.ml.not_product_training import (
    split_not_product_examples,
    train_not_product_classifier_artifacts,
)

from apps.ml.patron.train_cli import main


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

    assert split.metadata.strategy == "stratified_label_random_80_20_by_example_hash"
    assert split.metadata.seed == 20260527
    assert split.metadata.train_label_counts == {"not_product": 4, "product": 8}
    assert split.metadata.eval_label_counts == {"not_product": 1, "product": 2}


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
    assert isinstance(loaded_model, NotProductClassifierModel)
    assert loaded_model.model_version == "v0"
    assert metadata["model_name"] == "Patron"
    assert metadata["model_version"] == "v0"
    assert metadata["model_type"] == "rule_guarded_token_naive_bayes_baseline"
    assert metadata["feature_schema_version"] == "patron_features/v2"
    assert metadata["thresholds"] == {"not_product": 0.7}
    assert metadata["score_normalization"] == "average_token_log_likelihood"
    assert metadata["training_split"]["eval_label_counts"] == {
        "not_product": 1,
        "product": 2,
    }
    assert result.error_report_path.exists()
    assert (tmp_path / "models" / "current").resolve() == result.model_dir


def test_patron_train_cli_trains_from_dataset(tmp_path, capsys) -> None:
    model_dir = tmp_path / "models" / "v0"
    dataset_path = model_dir / "dataset.jsonl"
    model_dir.mkdir(parents=True)
    _write_dataset(dataset_path)

    exit_code = main(
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
