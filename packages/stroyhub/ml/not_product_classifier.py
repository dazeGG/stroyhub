from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stroyhub.catalog.tokenization import tokenize_normalized_text
from stroyhub.ml.not_product_labels import NotProductLabel
from stroyhub.parsers.common import normalize_title

PATRON_MODEL_NAME = "Patron"
NOT_PRODUCT_FEATURE_SCHEMA_VERSION = "patron_features/v2"
NOT_PRODUCT_LABEL: NotProductLabel = "not_product"
PRODUCT_LABEL: NotProductLabel = "product"
DEFAULT_NOT_PRODUCT_THRESHOLD = 0.70
LAPLACE_ALPHA = 1.0


@dataclass(frozen=True, kw_only=True)
class NotProductExample:
    example_hash: str
    label: NotProductLabel
    text: str
    title: str
    source: str


@dataclass(frozen=True, kw_only=True)
class NotProductPrediction:
    label: NotProductLabel
    not_product_probability: float
    confidence: float


@dataclass(frozen=True, kw_only=True)
class NotProductClassifierModel:
    model_version: str
    threshold: float
    alpha: float
    class_log_priors: dict[NotProductLabel, float]
    token_counts_by_label: dict[NotProductLabel, dict[str, int]]
    total_token_counts_by_label: dict[NotProductLabel, int]
    vocabulary: tuple[str, ...]

    def predict(self, text: str) -> NotProductPrediction:
        if _matches_not_product_rule(text):
            return NotProductPrediction(
                label=NOT_PRODUCT_LABEL,
                not_product_probability=1.0,
                confidence=1.0,
            )

        not_product_probability = self.not_product_probability(text)
        if not_product_probability >= self.threshold:
            label = NOT_PRODUCT_LABEL
            confidence = not_product_probability
        else:
            label = PRODUCT_LABEL
            confidence = 1.0 - not_product_probability
        return NotProductPrediction(
            label=label,
            not_product_probability=not_product_probability,
            confidence=confidence,
        )

    def not_product_probability(self, text: str) -> float:
        scores = self._class_log_scores(text)
        product_score = scores[PRODUCT_LABEL]
        not_product_score = scores[NOT_PRODUCT_LABEL]
        max_score = max(product_score, not_product_score)
        product_exp = math.exp(product_score - max_score)
        not_product_exp = math.exp(not_product_score - max_score)
        return not_product_exp / (product_exp + not_product_exp)

    def _class_log_scores(self, text: str) -> dict[NotProductLabel, float]:
        token_counts = Counter(_tokens(text))
        return {
            PRODUCT_LABEL: self._class_log_score(PRODUCT_LABEL, token_counts),
            NOT_PRODUCT_LABEL: self._class_log_score(NOT_PRODUCT_LABEL, token_counts),
        }

    def _class_log_score(
        self,
        label: NotProductLabel,
        token_counts: Counter[str],
    ) -> float:
        label_token_counts = self.token_counts_by_label.get(label, {})
        total_tokens = self.total_token_counts_by_label.get(label, 0)
        vocabulary_size = max(1, len(self.vocabulary))
        denominator = total_tokens + self.alpha * vocabulary_size
        score = self.class_log_priors[label]
        token_evidence = 0.0
        token_total = 0
        for token, count in token_counts.items():
            token_count = label_token_counts.get(token, 0)
            likelihood = (token_count + self.alpha) / denominator
            token_evidence += count * math.log(likelihood)
            token_total += count
        if token_total:
            score += token_evidence / token_total
        return score


def load_not_product_examples(path: str | Path) -> list[NotProductExample]:
    examples: list[NotProductExample] = []
    with Path(path).open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSONL record at {path}:{line_number}") from error
            examples.append(not_product_example_from_record(payload))
    return examples


def not_product_example_from_record(payload: object) -> NotProductExample:
    if not isinstance(payload, dict):
        raise ValueError("not-product dataset record must be a JSON object")

    label = _label(payload.get("label"))
    example_hash = _required_str(payload.get("example_hash"), "example_hash")
    source = _required_str(payload.get("source"), "source")
    product = payload.get("product")
    title = ""
    if isinstance(product, dict):
        raw_title = product.get("title")
        title = "" if raw_title is None else str(raw_title)

    return NotProductExample(
        example_hash=example_hash,
        label=label,
        text=build_not_product_text(payload),
        title=title,
        source=source,
    )


def build_not_product_text(payload: dict[str, Any]) -> str:
    product = _dict_value(payload.get("product"))
    latest_price = _dict_value(payload.get("latest_price"))

    parts = [
        _text(payload.get("source")),
        _text(product.get("title")),
        _text(product.get("normalized_title")),
    ]
    if latest_price:
        price_kind = normalize_title(_text(latest_price.get("price_kind")))
        if price_kind:
            parts.append(f"price_kind_{price_kind}")
        parts.append("price_present" if latest_price.get("price") else "price_missing")
    return normalize_title(" ".join(part for part in parts if part))


def _matches_not_product_rule(text: str) -> bool:
    normalized = normalize_title(text)
    if "price_kind_from" in normalized or "price_kind_range" in normalized:
        return True
    return (
        "2gis" in normalized
        and "price_kind_unknown" in normalized
        and "price_missing" in normalized
    )


def train_not_product_classifier_baseline(
    *,
    model_version: str,
    examples: list[NotProductExample],
    threshold: float = DEFAULT_NOT_PRODUCT_THRESHOLD,
    alpha: float = LAPLACE_ALPHA,
) -> NotProductClassifierModel:
    if not examples:
        raise ValueError("Patron needs at least one training example")
    labels = {example.label for example in examples}
    if labels != {PRODUCT_LABEL, NOT_PRODUCT_LABEL}:
        raise ValueError("Patron needs both product and not_product examples")

    token_counts_by_label: dict[NotProductLabel, Counter[str]] = {
        PRODUCT_LABEL: Counter(),
        NOT_PRODUCT_LABEL: Counter(),
    }
    total_token_counts_by_label: dict[NotProductLabel, int] = {
        PRODUCT_LABEL: 0,
        NOT_PRODUCT_LABEL: 0,
    }
    vocabulary: set[str] = set()

    for example in examples:
        tokens = _tokens(example.text)
        token_counts_by_label[example.label].update(tokens)
        total_token_counts_by_label[example.label] += len(tokens)
        vocabulary.update(tokens)

    # Balanced priors prevent the rare class from being suppressed by the
    # current 99%/1% dataset ratio while keeping evaluation on real data.
    class_log_priors: dict[NotProductLabel, float] = {
        PRODUCT_LABEL: math.log(0.5),
        NOT_PRODUCT_LABEL: math.log(0.5),
    }

    return NotProductClassifierModel(
        model_version=model_version,
        threshold=threshold,
        alpha=alpha,
        class_log_priors=class_log_priors,
        token_counts_by_label={
            PRODUCT_LABEL: dict(token_counts_by_label[PRODUCT_LABEL]),
            NOT_PRODUCT_LABEL: dict(token_counts_by_label[NOT_PRODUCT_LABEL]),
        },
        total_token_counts_by_label=total_token_counts_by_label,
        vocabulary=tuple(sorted(vocabulary)),
    )


def _tokens(text: str) -> tuple[str, ...]:
    return tokenize_normalized_text(normalize_title(text))


def _dict_value(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _required_str(value: object, field_name: str) -> str:
    if value is None or not str(value):
        raise ValueError(f"not-product dataset record must include {field_name}")
    return str(value)


def _label(value: object) -> NotProductLabel:
    if value == PRODUCT_LABEL:
        return PRODUCT_LABEL
    if value == NOT_PRODUCT_LABEL:
        return NOT_PRODUCT_LABEL
    raise ValueError("label must be product or not_product")
