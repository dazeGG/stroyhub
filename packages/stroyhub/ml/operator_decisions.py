from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from stroyhub.db.repositories import (
    JsonObject,
    OperatorDecisionFilters,
    OperatorDecisionRepository,
)
from stroyhub.models.tables import OperatorDecision

NormalizationOutcome = Literal["accepted", "rejected"]
PredictorDecision = Literal["accept", "reject"]


@dataclass(frozen=True, kw_only=True)
class CategoryDecisionExample:
    source_product_id: int
    category_id: int
    candidate_category_ids: tuple[int, ...]
    actor: str | None
    decided_at: datetime
    evidence: JsonObject | None
    alternatives: JsonObject | None


@dataclass(frozen=True, kw_only=True)
class NormalizationDecisionExample:
    source_product_id: int
    canonical_product_id: int
    product_match_id: int | None
    outcome: NormalizationOutcome
    action: str
    actor: str | None
    decided_at: datetime
    evidence: JsonObject | None
    alternatives: JsonObject | None


@dataclass(frozen=True, kw_only=True)
class CategoryPrediction:
    source_product_id: int
    ranked_category_ids: tuple[int, ...]


@dataclass(frozen=True, kw_only=True)
class CategoryPredictionMetrics:
    label_count: int
    prediction_count: int
    missing_prediction_count: int
    top_1_accuracy: float
    top_n_accuracy: float
    top_n: int


@dataclass(frozen=True, kw_only=True)
class NormalizationPrediction:
    source_product_id: int
    canonical_product_id: int
    decision: PredictorDecision
    auto_accept: bool = False
    safety_checks_passed: bool = False
    explanation: JsonObject | None = None


@dataclass(frozen=True, kw_only=True)
class NormalizationPredictionMetrics:
    label_count: int
    prediction_count: int
    precision: float
    recall: float
    unsafe_auto_accept_count: int
    auto_accept_count: int
    unsafe_auto_accept_rate: float


class OperatorDecisionDatasetBuilder:
    def __init__(self, session: Session) -> None:
        self._session = session

    def category_examples(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CategoryDecisionExample]:
        decisions = OperatorDecisionRepository(self._session).list(
            OperatorDecisionFilters(
                decision_type="categorization",
                action="set_category_override",
                limit=limit,
                offset=offset,
            )
        )
        examples: list[CategoryDecisionExample] = []
        for decision in decisions:
            if decision.source_product_id is None or decision.category_id is None:
                continue
            examples.append(
                CategoryDecisionExample(
                    source_product_id=decision.source_product_id,
                    category_id=decision.category_id,
                    candidate_category_ids=_candidate_category_ids(decision),
                    actor=decision.actor,
                    decided_at=decision.decided_at,
                    evidence=decision.evidence,
                    alternatives=decision.alternatives,
                )
            )
        return examples

    def normalization_examples(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[NormalizationDecisionExample]:
        decisions = OperatorDecisionRepository(self._session).list(
            OperatorDecisionFilters(
                decision_type="normalization",
                limit=limit,
                offset=offset,
            )
        )
        examples: list[NormalizationDecisionExample] = []
        for decision in decisions:
            if decision.source_product_id is None or decision.canonical_product_id is None:
                continue
            outcome = _normalization_outcome(decision)
            if outcome is None:
                continue
            examples.append(
                NormalizationDecisionExample(
                    source_product_id=decision.source_product_id,
                    canonical_product_id=decision.canonical_product_id,
                    product_match_id=decision.product_match_id,
                    outcome=outcome,
                    action=decision.action,
                    actor=decision.actor,
                    decided_at=decision.decided_at,
                    evidence=decision.evidence,
                    alternatives=decision.alternatives,
                )
            )
        return examples


def export_operator_decisions_jsonl(decisions: list[OperatorDecision]) -> str:
    return "".join(
        json.dumps(_decision_to_json(decision), ensure_ascii=False) + "\n"
        for decision in decisions
    )


def evaluate_category_predictions(
    labels: list[CategoryDecisionExample],
    predictions: list[CategoryPrediction],
    *,
    top_n: int = 3,
) -> CategoryPredictionMetrics:
    predictions_by_product = {
        prediction.source_product_id: prediction for prediction in predictions
    }
    top_1_hits = 0
    top_n_hits = 0
    missing = 0

    for label in labels:
        prediction = predictions_by_product.get(label.source_product_id)
        if prediction is None:
            missing += 1
            continue
        ranked_ids = prediction.ranked_category_ids
        if ranked_ids[:1] == (label.category_id,):
            top_1_hits += 1
        if label.category_id in ranked_ids[:top_n]:
            top_n_hits += 1

    return CategoryPredictionMetrics(
        label_count=len(labels),
        prediction_count=len(predictions),
        missing_prediction_count=missing,
        top_1_accuracy=_safe_divide(top_1_hits, len(labels)),
        top_n_accuracy=_safe_divide(top_n_hits, len(labels)),
        top_n=top_n,
    )


def evaluate_normalization_predictions(
    labels: list[NormalizationDecisionExample],
    predictions: list[NormalizationPrediction],
) -> NormalizationPredictionMetrics:
    labels_by_pair = {
        (label.source_product_id, label.canonical_product_id): label.outcome
        for label in labels
    }
    accepted_pairs = {
        pair for pair, outcome in labels_by_pair.items() if outcome == "accepted"
    }
    true_positive = 0
    false_positive = 0
    auto_accept_count = 0
    unsafe_auto_accept_count = 0

    for prediction in predictions:
        pair = (prediction.source_product_id, prediction.canonical_product_id)
        expected = labels_by_pair.get(pair)
        predicted_accept = prediction.decision == "accept"
        if predicted_accept and expected == "accepted":
            true_positive += 1
        elif predicted_accept and expected != "accepted":
            false_positive += 1

        if prediction.auto_accept:
            auto_accept_count += 1
            if (
                expected != "accepted"
                or not prediction.safety_checks_passed
                or not prediction.explanation
            ):
                unsafe_auto_accept_count += 1

    predicted_accepted_pairs = {
        (prediction.source_product_id, prediction.canonical_product_id)
        for prediction in predictions
        if prediction.decision == "accept"
    }
    false_negative = len(accepted_pairs - predicted_accepted_pairs)

    return NormalizationPredictionMetrics(
        label_count=len(labels),
        prediction_count=len(predictions),
        precision=_safe_divide(true_positive, true_positive + false_positive),
        recall=_safe_divide(true_positive, true_positive + false_negative),
        unsafe_auto_accept_count=unsafe_auto_accept_count,
        auto_accept_count=auto_accept_count,
        unsafe_auto_accept_rate=_safe_divide(unsafe_auto_accept_count, auto_accept_count),
    )


def _candidate_category_ids(decision: OperatorDecision) -> tuple[int, ...]:
    ids: list[int] = []
    items = decision.alternatives.get("items", []) if decision.alternatives else []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("category_id")
            if isinstance(raw_id, int):
                ids.append(raw_id)
    if decision.category_id is not None:
        ids.append(decision.category_id)
    return _unique_positive_ids(ids)


def _normalization_outcome(decision: OperatorDecision) -> NormalizationOutcome | None:
    if decision.action in {
        "attach_to_existing",
        "create_normalized_product",
        "accept",
    }:
        return "accepted"
    if decision.action in {"reject", "reject_suggestion"}:
        return "rejected"
    return None


def _unique_positive_ids(values: list[int]) -> tuple[int, ...]:
    seen: set[int] = set()
    unique_values: list[int] = []
    for value in values:
        if value <= 0 or value in seen:
            continue
        unique_values.append(value)
        seen.add(value)
    return tuple(unique_values)


def _decision_to_json(decision: OperatorDecision) -> dict[str, object]:
    payload = {
        "id": decision.id,
        "decision_type": decision.decision_type,
        "action": decision.action,
        "entity_type": decision.entity_type,
        "entity_id": decision.entity_id,
        "source_product_id": decision.source_product_id,
        "canonical_product_id": decision.canonical_product_id,
        "product_match_id": decision.product_match_id,
        "category_id": decision.category_id,
        "actor": decision.actor,
        "reason": decision.reason,
        "previous_state": decision.previous_state,
        "new_state": decision.new_state,
        "evidence": decision.evidence,
        "alternatives": decision.alternatives,
        "metadata": decision.decision_metadata,
        "decided_at": decision.decided_at.isoformat(),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
