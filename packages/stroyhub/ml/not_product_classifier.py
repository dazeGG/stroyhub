from __future__ import annotations

import json
import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import joblib

from stroyhub.catalog.tokenization import tokenize_normalized_text
from stroyhub.ml.not_product_labels import NotProductLabel
from stroyhub.parsers.common import normalize_title

PATRON_MODEL_NAME = "Patron"
NOT_PRODUCT_FEATURE_SCHEMA_VERSION = "patron_features/v3"
NOT_PRODUCT_LABEL: NotProductLabel = "not_product"
PRODUCT_LABEL: NotProductLabel = "product"
DEFAULT_NOT_PRODUCT_THRESHOLD = 0.70
LAPLACE_ALPHA = 1.0
LINEAR_DEFAULT_EPOCHS = 18
LINEAR_DEFAULT_LEARNING_RATE = 0.22
LINEAR_DEFAULT_L2 = 0.0005
LINEAR_DEFAULT_MAX_FEATURES = 45000

_DIMENSION_PATTERN = re.compile(
    r"\d+(?:[,.]\d+)?\s*(?:x|х|\*)\s*\d+|\d+(?:[,.]\d+)?\s*(?:кг|мм|см|м|л|шт|м2|м3)",
    re.IGNORECASE,
)
_GENERIC_TITLES = frozenset(
    {
        "товар",
        "разное",
        "прочее",
        "каталог",
        "услуги",
        "работы",
        "материалы",
        "комплектующие",
        "запчасти",
    }
)


@dataclass(frozen=True, kw_only=True)
class NotProductExample:
    example_hash: str
    label: NotProductLabel
    text: str
    title: str
    source: str
    label_source: str | None = None
    synthetic: bool = False
    sample_weight: float = 1.0
    group_key: str | None = None


@dataclass(frozen=True, kw_only=True)
class NotProductPrediction:
    label: NotProductLabel
    not_product_probability: float
    confidence: float


class NotProductClassifierModelUnavailableError(FileNotFoundError):
    pass


@dataclass(frozen=True, kw_only=True)
class NotProductClassifierResult:
    label: NotProductLabel
    not_product_probability: float
    confidence: float
    model_name: str
    model_version: str
    feature_schema_version: str
    threshold: float


class NotProductClassifierModelLike(Protocol):
    @property
    def model_version(self) -> str:
        pass

    @property
    def threshold(self) -> float:
        pass

    def predict(self, text: str) -> NotProductPrediction:
        pass


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


@dataclass(frozen=True, kw_only=True)
class LinearNotProductClassifierModel:
    model_version: str
    threshold: float
    feature_schema_version: str
    weights: dict[str, float]
    bias: float
    idf: dict[str, float]
    vocabulary: tuple[str, ...]

    def predict(self, text: str) -> NotProductPrediction:
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
        score = self.bias
        for token, value in _tfidf_vector(_tokens(text), self.idf).items():
            score += self.weights.get(token, 0.0) * value
        return _sigmoid(score)


class PatronClassifier:
    def __init__(
        self,
        *,
        model: NotProductClassifierModelLike,
        metadata: dict[str, Any],
    ) -> None:
        self._model = model
        self._metadata = metadata

    @property
    def model_name(self) -> str:
        return str(self._metadata.get("model_name") or PATRON_MODEL_NAME)

    @property
    def model_version(self) -> str:
        return str(self._metadata.get("model_version") or self._model.model_version)

    @property
    def feature_schema_version(self) -> str:
        model_schema = getattr(self._model, "feature_schema_version", None)
        return str(
            self._metadata.get("feature_schema_version")
            or model_schema
            or NOT_PRODUCT_FEATURE_SCHEMA_VERSION
        )

    @property
    def not_product_threshold(self) -> float:
        thresholds = self._metadata.get("thresholds")
        if isinstance(thresholds, dict) and "not_product" in thresholds:
            return float(thresholds["not_product"])
        return self._model.threshold

    @classmethod
    def default(cls, *, root: Path | None = None) -> PatronClassifier:
        base_path = root or Path.cwd()
        return cls.load(base_path / ".var" / "ml" / "patron" / "models" / "current")

    @classmethod
    def load(cls, model_dir: str | Path) -> PatronClassifier:
        model_dir = Path(model_dir)
        model_path = model_dir / "model.joblib"
        metadata_path = model_dir / "metadata.json"
        if not model_path.exists() or not metadata_path.exists():
            raise NotProductClassifierModelUnavailableError(
                f"Patron model is unavailable at {model_dir}"
            )

        model = joblib.load(model_path)
        if not isinstance(model, (NotProductClassifierModel, LinearNotProductClassifierModel)):
            raise TypeError(f"unsupported Patron model artifact: {type(model)!r}")

        metadata = json.loads(metadata_path.read_text("utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("Patron metadata must be a JSON object")

        return cls(model=model, metadata=metadata)

    def predict_record(self, record: dict[str, Any]) -> NotProductClassifierResult:
        prediction = self._model.predict(build_not_product_text(record))
        return NotProductClassifierResult(
            label=prediction.label,
            not_product_probability=prediction.not_product_probability,
            confidence=prediction.confidence,
            model_name=self.model_name,
            model_version=self.model_version,
            feature_schema_version=self.feature_schema_version,
            threshold=self.not_product_threshold,
        )


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
        label_source=_optional_str(payload.get("label_source")),
        synthetic=bool(payload.get("synthetic", False)),
        sample_weight=_sample_weight(payload),
        group_key=_group_key(payload),
    )


def build_not_product_text(payload: dict[str, Any]) -> str:
    product = _dict_value(payload.get("product"))
    latest_price = _dict_value(payload.get("latest_price"))
    shop = _dict_value(payload.get("shop"))
    title = _text(product.get("title"))
    normalized_title = _text(product.get("normalized_title"))
    category_raw = _text(product.get("category_raw"))
    category_name = _text(product.get("category_name"))
    description = _text(product.get("description"))
    unit_raw = _text(product.get("unit_raw") or latest_price.get("unit_raw"))
    category_path = _text_list(product.get("category_path"))

    parts = [
        _text(payload.get("source")),
        _feature_token("source", _text(payload.get("source"))),
        _text(shop.get("name")),
        _feature_token("shop", _text(shop.get("name"))),
        title,
        normalized_title,
        category_raw,
        category_name,
        " ".join(category_path),
        description,
        unit_raw,
    ]
    parts.extend(_title_feature_tokens(title or normalized_title))
    if category_raw or category_name or category_path:
        parts.append("featurecategorypresent")
    else:
        parts.append("featurecategorymissing")
    if description:
        parts.append("featuredescriptionpresent")
    if unit_raw:
        parts.append("featureunitpresent")
    if latest_price:
        price_kind = normalize_title(_text(latest_price.get("price_kind")))
        if price_kind:
            parts.append(f"price_kind_{price_kind}")
            parts.append(_feature_token("pricekind", price_kind))
        parts.append("price_present" if latest_price.get("price") else "price_missing")
        parts.append(
            "featurepricepresent" if latest_price.get("price") else "featurepricemissing"
        )
        price_text = _text(latest_price.get("price_text"))
        if price_text:
            parts.append(price_text)
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


def train_not_product_classifier_linear(
    *,
    model_version: str,
    examples: list[NotProductExample],
    threshold: float = DEFAULT_NOT_PRODUCT_THRESHOLD,
    epochs: int = LINEAR_DEFAULT_EPOCHS,
    learning_rate: float = LINEAR_DEFAULT_LEARNING_RATE,
    l2: float = LINEAR_DEFAULT_L2,
    max_features: int = LINEAR_DEFAULT_MAX_FEATURES,
    seed: int = 20260527,
) -> LinearNotProductClassifierModel:
    if not examples:
        raise ValueError("Patron needs at least one training example")
    labels = {example.label for example in examples}
    if labels != {PRODUCT_LABEL, NOT_PRODUCT_LABEL}:
        raise ValueError("Patron needs both product and not_product examples")

    tokenized = [_tokens(example.text) for example in examples]
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))

    vocabulary = tuple(
        token
        for token, _ in sorted(
            document_frequency.items(),
            key=lambda item: (-item[1], item[0]),
        )[:max_features]
    )
    vocabulary_set = set(vocabulary)
    idf = {
        token: math.log((1 + len(examples)) / (1 + document_frequency[token])) + 1.0
        for token in vocabulary
    }
    vectors = [
        _tfidf_vector(
            tuple(token for token in tokens if token in vocabulary_set),
            idf,
        )
        for tokens in tokenized
    ]

    class_counts = Counter(example.label for example in examples)
    class_weights = {
        label: len(examples) / (2 * count)
        for label, count in class_counts.items()
        if count > 0
    }
    weights = {token: 0.0 for token in vocabulary}
    bias = 0.0
    rng = random.Random(seed)
    indices = list(range(len(examples)))

    for epoch in range(epochs):
        rng.shuffle(indices)
        step_size = learning_rate / math.sqrt(epoch + 1)
        for index in indices:
            example = examples[index]
            vector = vectors[index]
            target = 1.0 if example.label == NOT_PRODUCT_LABEL else 0.0
            score = bias + sum(weights[token] * value for token, value in vector.items())
            prediction = _sigmoid(score)
            effective_weight = example.sample_weight * class_weights[example.label]
            error = (prediction - target) * effective_weight
            bias -= step_size * error
            for token, value in vector.items():
                weights[token] -= step_size * (error * value + l2 * weights[token])

    return LinearNotProductClassifierModel(
        model_version=model_version,
        threshold=threshold,
        feature_schema_version=NOT_PRODUCT_FEATURE_SCHEMA_VERSION,
        weights={token: weight for token, weight in weights.items() if weight},
        bias=bias,
        idf=idf,
        vocabulary=vocabulary,
    )


def _tokens(text: str) -> tuple[str, ...]:
    return tokenize_normalized_text(normalize_title(text))


def _tfidf_vector(tokens: tuple[str, ...], idf: dict[str, float]) -> dict[str, float]:
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = sum(counts.values())
    values = {
        token: (count / total) * idf[token]
        for token, count in counts.items()
        if token in idf
    }
    norm = math.sqrt(sum(value * value for value in values.values()))
    if not norm:
        return values
    return {token: value / norm for token, value in values.items()}


def _dict_value(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    if isinstance(value, tuple):
        return [_text(item) for item in value if _text(item)]
    return []


def _sample_weight(payload: dict[str, Any]) -> float:
    explicit = payload.get("sample_weight")
    if explicit is not None:
        try:
            weight = float(explicit)
        except (TypeError, ValueError) as error:
            raise ValueError("sample_weight must be a number") from error
        return max(0.0, weight)
    if payload.get("synthetic") is True:
        return 0.35
    return 1.0


def _group_key(payload: dict[str, Any]) -> str:
    product = _dict_value(payload.get("product"))
    shop = _dict_value(payload.get("shop"))
    parts = [
        _text(payload.get("source")),
        _text(shop.get("name")),
        _text(product.get("normalized_title") or product.get("title")),
        _text(product.get("category_raw") or product.get("category_name")),
    ]
    return normalize_title(" ".join(part for part in parts if part))


def _title_feature_tokens(title: str) -> list[str]:
    normalized = normalize_title(title)
    tokens = _tokens(normalized)
    features: list[str] = []
    if not tokens:
        features.append("featuretitleempty")
        return features
    if len(tokens) == 1:
        features.append("featuretitleoneword")
    elif len(tokens) <= 3:
        features.append("featuretitleshort")
    elif len(tokens) >= 10:
        features.append("featuretitlelong")
    if normalized in _GENERIC_TITLES:
        features.append("featuretitlegeneric")
    if any(char.isdigit() for char in title):
        features.append("featuretitlehasdigit")
    if _DIMENSION_PATTERN.search(title):
        features.append("featuretitlehasdimension")
    if any(token in {"от", "до"} for token in tokens):
        features.append("featuretitlehasrange")
    return features


def _feature_token(prefix: str, value: str) -> str:
    normalized = "".join(_tokens(value))
    return f"feature{prefix}{normalized}" if normalized else ""


def _sigmoid(score: float) -> float:
    if score >= 0:
        z = math.exp(-score)
        return 1.0 / (1.0 + z)
    z = math.exp(score)
    return z / (1.0 + z)


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
