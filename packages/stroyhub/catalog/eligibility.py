import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from stroyhub.catalog.attributes import extract_title_attributes
from stroyhub.catalog.tokenization import tokenize_title
from stroyhub.parsers.common import JsonObject, normalize_title, title_implies_from_price

CatalogEligibilityStatus = Literal["eligible", "needs_review", "ineligible"]

_PRICE_FROM_PATTERN = re.compile(r"(^|\s)от\s*\d", re.IGNORECASE)
_RANGE_PRICE_PATTERN = re.compile(r"\d+\s*(?:-|–|—)\s*\d+")
_GRADE_PATTERN = re.compile(r"^[мm]\d{2,3}$", re.IGNORECASE)
_GENERIC_TITLE_TOKENS = frozenset(
    {
        "арматура",
        "болты",
        "брус",
        "гвозди",
        "доска",
        "дюбели",
        "краска",
        "кирпич",
        "клей",
        "линолеум",
        "песок",
        "плитка",
        "профиль",
        "саморезы",
        "смеси",
        "труба",
        "фанера",
        "цемент",
        "щебень",
        "шурупы",
    }
)
_GENERIC_MODIFIER_TOKENS = frozenset(
    {
        "влагостойкий",
        "гипсовая",
        "деревянные",
        "желтые",
        "красный",
        "кровельные",
        "металлический",
        "мытый",
        "оцинкованные",
        "плиточный",
        "полнотелый",
        "самонарезающие",
        "серый",
        "строительные",
        "сухие",
        "черные",
    }
)
_SPECIFIC_ATTRIBUTE_KINDS = frozenset(
    {
        "area",
        "dimension",
        "length",
        "package_count",
        "thickness",
        "volume",
        "weight",
    }
)


@dataclass(frozen=True, kw_only=True)
class ProductEligibilityInput:
    source: str
    title: str
    price: Decimal | None
    raw: JsonObject | None = None
    price_kind: str = "exact"


@dataclass(frozen=True, kw_only=True)
class ProductEligibility:
    status: CatalogEligibilityStatus
    confidence: Decimal
    reasons: tuple[str, ...]
    score: int
    method: str = "rules"
    model_name: str | None = None
    model_version: str | None = None
    feature_schema_version: str | None = None
    not_product_probability: Decimal | None = None
    thresholds: JsonObject | None = None

    @property
    def is_matchable(self) -> bool:
        return self.status == "eligible"

    @property
    def is_not_product(self) -> bool:
        return self.status == "ineligible"

    def as_raw(self) -> JsonObject:
        raw: JsonObject = {
            "status": self.status,
            "confidence": str(self.confidence),
            "score": self.score,
            "reasons": list(self.reasons),
            "method": self.method,
        }
        if self.model_name is not None:
            raw["model_name"] = self.model_name
        if self.model_version is not None:
            raw["model_version"] = self.model_version
        if self.feature_schema_version is not None:
            raw["feature_schema_version"] = self.feature_schema_version
        if self.not_product_probability is not None:
            raw["not_product_probability"] = str(self.not_product_probability)
        if self.thresholds is not None:
            raw["thresholds"] = self.thresholds
        return raw


def evaluate_product_eligibility(data: ProductEligibilityInput) -> ProductEligibility:
    if data.source != "2gis":
        return ProductEligibility(
            status="eligible",
            confidence=Decimal("1.000"),
            reasons=("trusted_source_type",),
            score=100,
        )

    reasons = _hard_constraint_reasons(data)
    tokens = tokenize_title(data.title).tokens
    attributes = extract_title_attributes(data.title)
    has_specific_attribute = any(
        attribute.kind in _SPECIFIC_ATTRIBUTE_KINDS for attribute in attributes
    )
    has_protected_token = any(any(char.isdigit() for char in token) for token in tokens)
    has_grade = any(_GRADE_PATTERN.match(token) for token in tokens)
    generic_title = _is_generic_title(tokens)

    if generic_title:
        reasons.append("generic_title")
    if not (has_specific_attribute or has_protected_token or has_grade):
        reasons.append("no_specific_product_attributes")

    if (
        "missing_price" in reasons
        or "non_exact_price" in reasons
        or "approximate_offer" in reasons
    ):
        return _result("ineligible", reasons, score=0)

    if generic_title and not (has_specific_attribute or has_protected_token or has_grade):
        return _result("ineligible", reasons, score=10)

    score = 100
    if generic_title:
        score -= 45
    if not has_specific_attribute:
        score -= 20
    if not has_protected_token:
        score -= 15

    if score < 70:
        return _result("needs_review", reasons or ["weak_product_specificity"], score=score)

    return _result("eligible", reasons or ["exact_price_and_specific_title"], score=score)


def evaluate_product_hard_constraints(
    data: ProductEligibilityInput,
) -> ProductEligibility | None:
    if data.source != "2gis":
        return None

    reasons = _hard_constraint_reasons(data)
    if not reasons:
        return None

    return _result("ineligible", reasons, score=0)


def _hard_constraint_reasons(data: ProductEligibilityInput) -> list[str]:
    reasons: list[str] = []
    if data.price is None:
        reasons.append("missing_price")
    if (
        data.price_kind in {"from", "range"}
        or _has_from_or_range_price(data.raw)
        or title_implies_from_price(data.title)
    ):
        reasons.append("non_exact_price")
    if _has_approximate_offer_notice(data.raw):
        reasons.append("approximate_offer")

    return reasons


def is_matchable_source_product(raw: JsonObject | None, *, is_not_product: bool) -> bool:
    if is_not_product:
        return False

    eligibility = _raw_eligibility(raw)
    if eligibility is None:
        return False

    return eligibility.get("status") == "eligible"


def with_catalog_eligibility(
    raw: JsonObject | None,
    eligibility: ProductEligibility,
    *,
    existing_raw: JsonObject | None = None,
) -> JsonObject:
    updated: JsonObject = dict(raw or {})
    operator_review = _operator_review(existing_raw)
    if operator_review is not None:
        updated["operator_review"] = operator_review
    updated["catalog_eligibility"] = eligibility.as_raw()
    return updated


def operator_data_problem_mark(raw: JsonObject | None) -> bool | None:
    operator_review = _operator_review(raw)
    if operator_review is None:
        return None

    data_problem = operator_review.get("data_problem")
    if not isinstance(data_problem, dict):
        return None

    marked = data_problem.get("marked")
    return marked if isinstance(marked, bool) else None


def _result(
    status: CatalogEligibilityStatus,
    reasons: list[str],
    *,
    score: int,
) -> ProductEligibility:
    bounded_score = min(100, max(0, score))
    return ProductEligibility(
        status=status,
        confidence=Decimal(bounded_score).scaleb(-2).quantize(Decimal("0.001")),
        reasons=tuple(dict.fromkeys(reasons)),
        score=bounded_score,
    )


def _is_generic_title(tokens: tuple[str, ...]) -> bool:
    if not tokens:
        return True

    token_set = set(tokens)
    if len(tokens) == 1 and tokens[0] in _GENERIC_TITLE_TOKENS:
        return True

    meaningful_tokens = token_set - _GENERIC_MODIFIER_TOKENS
    return (
        len(tokens) <= 3
        and bool(token_set & _GENERIC_TITLE_TOKENS)
        and meaningful_tokens <= _GENERIC_TITLE_TOKENS
    )


def _has_from_or_range_price(raw: JsonObject | None) -> bool:
    if raw is None:
        return False

    offer = raw.get("offer")
    if not isinstance(offer, dict):
        return False

    return _contains_price_from_signal(offer)


def _has_approximate_offer_notice(raw: JsonObject | None) -> bool:
    if raw is None:
        return False

    product = raw.get("product")
    if isinstance(product, dict) and _contains_approximate_offer_notice(
        product.get("description")
    ):
        return True

    return _contains_approximate_offer_notice(raw.get("description"))


def _contains_approximate_offer_notice(value: object) -> bool:
    if not isinstance(value, str):
        return False

    normalized = normalize_title(value)
    return (
        "цена указана ориентировочно" in normalized
        or "не является публичной оферт" in normalized
    )


def _contains_price_from_signal(value: object, *, key: str | None = None) -> bool:
    if isinstance(value, dict):
        for nested_key, nested_value in value.items():
            normalized_key = normalize_title(str(nested_key))
            if normalized_key in {"from", "min", "min_price", "price_from"}:
                return True
            if _contains_price_from_signal(nested_value, key=normalized_key):
                return True
        return False

    if isinstance(value, list):
        return any(_contains_price_from_signal(item, key=key) for item in value)

    if isinstance(value, str):
        normalized = normalize_title(value)
        if _PRICE_FROM_PATTERN.search(normalized):
            return True
        return key in {"price", "value", "label", "text"} and bool(
            _RANGE_PRICE_PATTERN.search(normalized)
        )

    return False


def _raw_eligibility(raw: JsonObject | None) -> dict[str, Any] | None:
    if raw is None:
        return None

    eligibility = raw.get("catalog_eligibility")
    return eligibility if isinstance(eligibility, dict) else None


def _operator_review(raw: JsonObject | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    operator_review = raw.get("operator_review")
    return dict(operator_review) if isinstance(operator_review, dict) else None
