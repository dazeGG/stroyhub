from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date

from stroyhub.ml.labels import VerifierOutcome
from stroyhub.ml.verifier import (
    CategoryVerifierBaselineModel,
    CategoryVerifierExample,
    VerifierDecision,
)


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierSplitMetadata:
    strategy: str
    train_ratio: float
    seed: int
    run_date: str
    train_label_count: int
    eval_label_count: int
    train_product_count: int
    eval_product_count: int


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierSplit:
    train_examples: list[CategoryVerifierExample]
    eval_examples: list[CategoryVerifierExample]
    metadata: CategoryVerifierSplitMetadata


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierMetrics:
    label_count: int
    match_count: int
    no_match_count: int
    accuracy: float
    precision: float
    recall: float
    f1: float
    uncertain_count: int
    error_count: int


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierError:
    product_id: int
    category_id: int
    expected: VerifierOutcome
    decision: VerifierDecision
    confidence: float


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierEvaluation:
    metrics: CategoryVerifierMetrics
    errors: list[CategoryVerifierError]


def split_category_verifier_examples(
    examples: list[CategoryVerifierExample],
    *,
    run_date: date,
    train_ratio: float = 0.80,
) -> CategoryVerifierSplit:
    product_ids = sorted({example.product_id for example in examples})
    seed = int(run_date.strftime("%Y%m%d"))
    shuffled_product_ids = product_ids[:]
    random.Random(seed).shuffle(shuffled_product_ids)

    if len(shuffled_product_ids) <= 1:
        eval_product_ids: set[int] = set()
    else:
        eval_count = max(1, round(len(shuffled_product_ids) * (1 - train_ratio)))
        eval_product_ids = set(shuffled_product_ids[:eval_count])

    train_examples = [
        example for example in examples if example.product_id not in eval_product_ids
    ]
    eval_examples = [example for example in examples if example.product_id in eval_product_ids]

    return CategoryVerifierSplit(
        train_examples=train_examples,
        eval_examples=eval_examples,
        metadata=CategoryVerifierSplitMetadata(
            strategy="source_product_id_random_80_20",
            train_ratio=train_ratio,
            seed=seed,
            run_date=run_date.isoformat(),
            train_label_count=len(train_examples),
            eval_label_count=len(eval_examples),
            train_product_count=len({example.product_id for example in train_examples}),
            eval_product_count=len({example.product_id for example in eval_examples}),
        ),
    )


def evaluate_category_verifier(
    *,
    model: CategoryVerifierBaselineModel,
    examples: list[CategoryVerifierExample],
) -> CategoryVerifierEvaluation:
    true_positive = 0
    false_positive = 0
    false_negative = 0
    correct = 0
    uncertain_count = 0
    errors: list[CategoryVerifierError] = []

    for example in examples:
        prediction = model.verify(example.features)
        expected = example.outcome
        if prediction.decision == "uncertain":
            uncertain_count += 1
        if prediction.decision == expected:
            correct += 1
        else:
            errors.append(
                CategoryVerifierError(
                    product_id=example.product_id,
                    category_id=example.category_id,
                    expected=expected,
                    decision=prediction.decision,
                    confidence=prediction.confidence,
                )
            )

        if prediction.decision == "match" and expected == "match":
            true_positive += 1
        elif prediction.decision == "match" and expected == "no_match":
            false_positive += 1
        elif prediction.decision != "match" and expected == "match":
            false_negative += 1

    precision = _safe_divide(true_positive, true_positive + false_positive)
    recall = _safe_divide(true_positive, true_positive + false_negative)
    f1 = _safe_divide(2 * precision * recall, precision + recall)

    return CategoryVerifierEvaluation(
        metrics=CategoryVerifierMetrics(
            label_count=len(examples),
            match_count=sum(1 for example in examples if example.outcome == "match"),
            no_match_count=sum(1 for example in examples if example.outcome == "no_match"),
            accuracy=_safe_divide(correct, len(examples)),
            precision=precision,
            recall=recall,
            f1=f1,
            uncertain_count=uncertain_count,
            error_count=len(errors),
        ),
        errors=errors,
    )


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
