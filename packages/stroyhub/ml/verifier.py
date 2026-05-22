from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from stroyhub.catalog.tokenization import tokenize_normalized_text
from stroyhub.ml.features import CategoryVerifierFeatureRow
from stroyhub.ml.labels import VerifierOutcome

VerifierDecision = Literal["match", "no_match", "uncertain"]

MATCH_THRESHOLD = 0.80
NO_MATCH_THRESHOLD = 0.35


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierExample:
    product_id: int
    category_id: int
    outcome: VerifierOutcome
    features: CategoryVerifierFeatureRow


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierPrediction:
    decision: VerifierDecision
    confidence: float


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierBaselineModel:
    model_version: str
    match_threshold: float
    no_match_threshold: float
    positive_tokens_by_category: dict[int, dict[str, int]]
    negative_tokens_by_category: dict[int, dict[str, int]]
    positive_tokens: dict[str, int]
    negative_tokens: dict[str, int]

    def verify(self, features: CategoryVerifierFeatureRow) -> CategoryVerifierPrediction:
        confidence = self.confidence(features)
        if confidence >= self.match_threshold:
            decision: VerifierDecision = "match"
        elif confidence <= self.no_match_threshold:
            decision = "no_match"
        else:
            decision = "uncertain"
        return CategoryVerifierPrediction(decision=decision, confidence=confidence)

    def confidence(self, features: CategoryVerifierFeatureRow) -> float:
        category_id = _int_feature(features.values.get("category.id"))
        product_tokens = set(tokenize_normalized_text(features.values["product.context_text"]))
        positive_weight = _token_weight(product_tokens, self.positive_tokens)
        negative_weight = _token_weight(product_tokens, self.negative_tokens)

        if category_id is not None:
            positive_weight += _token_weight(
                product_tokens,
                self.positive_tokens_by_category.get(category_id, {}),
            )
            negative_weight += _token_weight(
                product_tokens,
                self.negative_tokens_by_category.get(category_id, {}),
            )

        score = 0.50
        total_weight = positive_weight + negative_weight
        if total_weight:
            score += 0.30 * ((positive_weight - negative_weight) / total_weight)
        if features.values["pair.product_has_current_category"] == "1":
            score += 0.18
        if features.values["pair.raw_category_mentions_category"] == "1":
            score += 0.12
        if features.values["pair.title_mentions_category"] == "1":
            score += 0.08
        return min(max(score, 0.0), 1.0)


def train_category_verifier_baseline(
    *,
    model_version: str,
    examples: list[CategoryVerifierExample],
) -> CategoryVerifierBaselineModel:
    positive_tokens_by_category: dict[int, Counter[str]] = {}
    negative_tokens_by_category: dict[int, Counter[str]] = {}
    positive_tokens: Counter[str] = Counter()
    negative_tokens: Counter[str] = Counter()

    for example in examples:
        product_tokens = tokenize_normalized_text(example.features.values["product.context_text"])
        if example.outcome == "match":
            positive_tokens.update(product_tokens)
            positive_tokens_by_category.setdefault(example.category_id, Counter()).update(
                product_tokens
            )
        else:
            negative_tokens.update(product_tokens)
            negative_tokens_by_category.setdefault(example.category_id, Counter()).update(
                product_tokens
            )

    return CategoryVerifierBaselineModel(
        model_version=model_version,
        match_threshold=MATCH_THRESHOLD,
        no_match_threshold=NO_MATCH_THRESHOLD,
        positive_tokens_by_category=_freeze_nested_counters(positive_tokens_by_category),
        negative_tokens_by_category=_freeze_nested_counters(negative_tokens_by_category),
        positive_tokens=dict(positive_tokens),
        negative_tokens=dict(negative_tokens),
    )


def _token_weight(tokens: set[str], weights: dict[str, int]) -> int:
    return sum(weights.get(token, 0) for token in tokens)


def _freeze_nested_counters(counters: dict[int, Counter[str]]) -> dict[int, dict[str, int]]:
    return {key: dict(counter) for key, counter in counters.items()}


def _int_feature(value: str | None) -> int | None:
    if value is None or not value:
        return None
    return int(value)
