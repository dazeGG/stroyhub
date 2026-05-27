from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import joblib

from stroyhub.ml.not_product_classifier import (
    NOT_PRODUCT_FEATURE_SCHEMA_VERSION,
    NOT_PRODUCT_LABEL,
    PATRON_MODEL_NAME,
    PRODUCT_LABEL,
    NotProductClassifierModel,
    NotProductExample,
    load_not_product_examples,
    train_not_product_classifier_baseline,
)
from stroyhub.ml.not_product_labels import NotProductLabel


@dataclass(frozen=True, kw_only=True)
class NotProductSplitMetadata:
    strategy: str
    train_ratio: float
    seed: int
    run_date: str
    train_count: int
    eval_count: int
    train_label_counts: dict[str, int]
    eval_label_counts: dict[str, int]


@dataclass(frozen=True, kw_only=True)
class NotProductSplit:
    train_examples: list[NotProductExample]
    eval_examples: list[NotProductExample]
    metadata: NotProductSplitMetadata


@dataclass(frozen=True, kw_only=True)
class NotProductMetrics:
    label_count: int
    product_count: int
    not_product_count: int
    accuracy: float
    not_product_precision: float
    not_product_recall: float
    not_product_f1: float
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    error_count: int


@dataclass(frozen=True, kw_only=True)
class NotProductEvaluationError:
    example_hash: str
    expected: NotProductLabel
    predicted: NotProductLabel
    not_product_probability: float
    confidence: float
    title: str
    source: str


@dataclass(frozen=True, kw_only=True)
class NotProductEvaluation:
    metrics: NotProductMetrics
    errors: list[NotProductEvaluationError]


@dataclass(frozen=True, kw_only=True)
class NotProductTrainingResult:
    model_version: str
    model_dir: Path
    model_path: Path
    metadata_path: Path
    error_report_path: Path
    dataset_path: Path
    split: NotProductSplit
    evaluation: NotProductEvaluation


def split_not_product_examples(
    examples: list[NotProductExample],
    *,
    run_date: date,
    train_ratio: float = 0.80,
) -> NotProductSplit:
    if not 0.0 < train_ratio < 1.0:
        raise ValueError("train_ratio must be between 0 and 1")

    seed = int(run_date.strftime("%Y%m%d"))
    rng = random.Random(seed)
    by_label: dict[NotProductLabel, list[NotProductExample]] = {
        PRODUCT_LABEL: [],
        NOT_PRODUCT_LABEL: [],
    }
    for example in examples:
        by_label[example.label].append(example)

    train_examples: list[NotProductExample] = []
    eval_examples: list[NotProductExample] = []
    for label_examples in by_label.values():
        shuffled = sorted(label_examples, key=lambda example: example.example_hash)
        rng.shuffle(shuffled)
        if len(shuffled) <= 1:
            train_examples.extend(shuffled)
            continue

        eval_count = max(1, round(len(shuffled) * (1 - train_ratio)))
        eval_examples.extend(shuffled[:eval_count])
        train_examples.extend(shuffled[eval_count:])

    train_examples = sorted(train_examples, key=lambda example: example.example_hash)
    eval_examples = sorted(eval_examples, key=lambda example: example.example_hash)

    return NotProductSplit(
        train_examples=train_examples,
        eval_examples=eval_examples,
        metadata=NotProductSplitMetadata(
            strategy="stratified_label_random_80_20_by_example_hash",
            train_ratio=train_ratio,
            seed=seed,
            run_date=run_date.isoformat(),
            train_count=len(train_examples),
            eval_count=len(eval_examples),
            train_label_counts=_label_counts(train_examples),
            eval_label_counts=_label_counts(eval_examples),
        ),
    )


def evaluate_not_product_classifier(
    *,
    model: NotProductClassifierModel,
    examples: list[NotProductExample],
) -> NotProductEvaluation:
    true_positive = 0
    false_positive = 0
    false_negative = 0
    true_negative = 0
    errors: list[NotProductEvaluationError] = []

    for example in examples:
        prediction = model.predict(example.text)
        expected = example.label
        predicted = prediction.label

        if predicted == NOT_PRODUCT_LABEL and expected == NOT_PRODUCT_LABEL:
            true_positive += 1
        elif predicted == NOT_PRODUCT_LABEL and expected == PRODUCT_LABEL:
            false_positive += 1
        elif predicted == PRODUCT_LABEL and expected == NOT_PRODUCT_LABEL:
            false_negative += 1
        elif predicted == PRODUCT_LABEL and expected == PRODUCT_LABEL:
            true_negative += 1

        if predicted != expected:
            errors.append(
                NotProductEvaluationError(
                    example_hash=example.example_hash,
                    expected=expected,
                    predicted=predicted,
                    not_product_probability=prediction.not_product_probability,
                    confidence=prediction.confidence,
                    title=example.title,
                    source=example.source,
                )
            )

    precision = _safe_divide(true_positive, true_positive + false_positive)
    recall = _safe_divide(true_positive, true_positive + false_negative)
    f1 = _safe_divide(2 * precision * recall, precision + recall)
    correct = true_positive + true_negative

    return NotProductEvaluation(
        metrics=NotProductMetrics(
            label_count=len(examples),
            product_count=sum(1 for example in examples if example.label == PRODUCT_LABEL),
            not_product_count=sum(
                1 for example in examples if example.label == NOT_PRODUCT_LABEL
            ),
            accuracy=_safe_divide(correct, len(examples)),
            not_product_precision=precision,
            not_product_recall=recall,
            not_product_f1=f1,
            true_positive=true_positive,
            false_positive=false_positive,
            false_negative=false_negative,
            true_negative=true_negative,
            error_count=len(errors),
        ),
        errors=errors,
    )


def train_not_product_classifier_artifacts(
    *,
    dataset_path: Path,
    model_dir: Path,
    model_version: str,
    run_date: date,
    train_ratio: float = 0.80,
) -> NotProductTrainingResult:
    examples = load_not_product_examples(dataset_path)
    split = split_not_product_examples(
        examples,
        run_date=run_date,
        train_ratio=train_ratio,
    )
    model = train_not_product_classifier_baseline(
        model_version=model_version,
        examples=split.train_examples,
    )
    evaluation = evaluate_not_product_classifier(model=model, examples=split.eval_examples)

    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "model.joblib"
    metadata_path = model_dir / "metadata.json"
    error_report_path = model_dir / "eval_errors.jsonl"

    joblib.dump(model, model_path)
    metadata_path.write_text(
        json.dumps(
            _training_metadata(
                model=model,
                dataset_path=dataset_path,
                split=split,
                evaluation=evaluation,
                run_date=run_date,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_error_report(error_report_path, evaluation)
    _update_current_pointer(models_dir=model_dir.parent, model_version=model_dir.name)

    return NotProductTrainingResult(
        model_version=model_version,
        model_dir=model_dir,
        model_path=model_path,
        metadata_path=metadata_path,
        error_report_path=error_report_path,
        dataset_path=dataset_path,
        split=split,
        evaluation=evaluation,
    )


def _training_metadata(
    *,
    model: NotProductClassifierModel,
    dataset_path: Path,
    split: NotProductSplit,
    evaluation: NotProductEvaluation,
    run_date: date,
) -> dict[str, object]:
    return {
        "model_name": PATRON_MODEL_NAME,
        "model_version": model.model_version,
        "model_type": "rule_guarded_token_naive_bayes_baseline",
        "created_at": datetime.now(UTC).isoformat(),
        "run_date": run_date.isoformat(),
        "dataset_path": str(dataset_path),
        "feature_schema_version": NOT_PRODUCT_FEATURE_SCHEMA_VERSION,
        "thresholds": {
            "not_product": model.threshold,
        },
        "class_prior_policy": "balanced_0.5_0.5",
        "score_normalization": "average_token_log_likelihood",
        "laplace_alpha": model.alpha,
        "vocabulary_size": len(model.vocabulary),
        "training_split": asdict(split.metadata),
        "metrics": asdict(evaluation.metrics),
    }


def _write_error_report(path: Path, evaluation: NotProductEvaluation) -> None:
    with path.open("w", encoding="utf-8") as file:
        for error in evaluation.errors:
            file.write(json.dumps(asdict(error), ensure_ascii=False))
            file.write("\n")


def _update_current_pointer(*, models_dir: Path, model_version: str) -> None:
    current_path = models_dir / "current"
    if current_path.exists() or current_path.is_symlink():
        if current_path.is_dir() and not current_path.is_symlink():
            raise ValueError(f"{current_path} exists and is not a symlink")
        current_path.unlink()
    current_path.symlink_to(model_version, target_is_directory=True)


def _label_counts(examples: list[NotProductExample]) -> dict[str, int]:
    counts = Counter(example.label for example in examples)
    return {
        NOT_PRODUCT_LABEL: counts[NOT_PRODUCT_LABEL],
        PRODUCT_LABEL: counts[PRODUCT_LABEL],
    }


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
