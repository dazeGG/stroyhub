from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Literal

from stroyhub.catalog.product_suitability import ProductSuitabilityEvaluator
from stroyhub.ml.not_product_classifier import NotProductClassifierResult
from stroyhub.parsers.common import ParsedProduct, PriceKind


def test_product_suitability_uses_patron_for_any_source() -> None:
    evaluator = ProductSuitabilityEvaluator(
        patron=FakePatron(not_product_probability=0.95)
    )

    decision = evaluator.evaluate(_product(source="unicom", title="Брус"))

    assert decision.status == "ineligible"
    assert decision.is_not_product is True
    assert decision.method == "patron"
    assert decision.reasons == ("patron_not_product",)
    assert decision.model_name == "Patron"
    assert decision.model_version == "v-test"


def test_product_suitability_routes_uncertain_patron_predictions_to_review() -> None:
    evaluator = ProductSuitabilityEvaluator(
        patron=FakePatron(not_product_probability=0.55)
    )

    decision = evaluator.evaluate(_product(source="2gis", title="Цемент М500"))

    assert decision.status == "needs_review"
    assert decision.is_not_product is False
    assert decision.reasons == ("patron_uncertain",)
    assert decision.not_product_probability == Decimal("0.550")


def test_product_suitability_applies_non_exact_price_rule_before_patron() -> None:
    patron = FakePatron(not_product_probability=0.01)
    evaluator = ProductSuitabilityEvaluator(patron=patron)

    decision = evaluator.evaluate(
        _product(
            source="2gis",
            title="Брус от 100 *100 мм до 180*180 мм, длина 6 м",
            price_kind="from",
            raw={"offer": {"price": "от 29000 ₽"}},
        )
    )

    assert decision.status == "ineligible"
    assert decision.method == "rules"
    assert decision.reasons == ("non_exact_price",)
    assert patron.calls == 0


def test_product_suitability_applies_missing_price_rule_before_patron() -> None:
    patron = FakePatron(not_product_probability=0.01)
    evaluator = ProductSuitabilityEvaluator(patron=patron)

    decision = evaluator.evaluate(
        _product(
            source="2gis",
            title="Краска Dulux PROF Bindo 7 BW 2.5L",
            price=None,
            price_kind="unknown",
            raw={"offer": {"price_value": {"empty": {}}}},
        )
    )

    assert decision.status == "ineligible"
    assert decision.method == "rules"
    assert decision.reasons == ("missing_price",)
    assert patron.calls == 0


def test_product_suitability_applies_approximate_offer_rule_before_patron() -> None:
    patron = FakePatron(not_product_probability=0.01)
    evaluator = ProductSuitabilityEvaluator(patron=patron)

    decision = evaluator.evaluate(
        _product(
            source="2gis",
            title="Металлочерепица Grand Line 0.5 мм",
            raw={
                "offer": {"price": 1552},
                "product": {
                    "description": "Цена указана ориентировочно. Не является публичной офертой."
                },
            },
        )
    )

    assert decision.status == "ineligible"
    assert decision.method == "rules"
    assert decision.reasons == ("approximate_offer",)
    assert patron.calls == 0


def test_product_suitability_falls_back_to_rules_when_patron_is_unavailable() -> None:
    evaluator = ProductSuitabilityEvaluator(patron=None)

    decision = evaluator.evaluate(_product(source="2gis", title="Песок мытый"))

    assert decision.status == "ineligible"
    assert decision.method == "rules"
    assert decision.reasons == ("generic_title", "no_specific_product_attributes")


def test_product_suitability_preserves_operator_data_problem_review() -> None:
    evaluator = ProductSuitabilityEvaluator(
        patron=FakePatron(not_product_probability=0.95)
    )
    existing_product = SimpleNamespace(
        raw={
            "operator_review": {
                "data_problem": {
                    "marked": False,
                    "actor": "admin",
                }
            }
        }
    )

    decision = evaluator.evaluate(
        _product(source="2gis", title="Брус"),
        existing_product=existing_product,  # type: ignore[arg-type]
    )

    assert decision.status == "eligible"
    assert decision.is_not_product is False
    assert decision.method == "operator_review"


class FakePatron:
    def __init__(self, *, not_product_probability: float, threshold: float = 0.70) -> None:
        self._not_product_probability = not_product_probability
        self._threshold = threshold
        self.calls = 0

    def predict_record(self, record: dict[str, Any]) -> NotProductClassifierResult:
        self.calls += 1
        probability = self._not_product_probability
        label: Literal["not_product", "product"] = (
            "not_product" if probability >= self._threshold else "product"
        )
        confidence = probability if label == "not_product" else 1.0 - probability
        return NotProductClassifierResult(
            label=label,
            not_product_probability=probability,
            confidence=confidence,
            model_name="Patron",
            model_version="v-test",
            feature_schema_version="patron_features/v2",
            threshold=self._threshold,
        )


def _product(
    *,
    source: str,
    title: str,
    price: Decimal | None = Decimal("100.00"),
    price_kind: PriceKind = "exact",
    raw: dict[str, Any] | None = None,
) -> ParsedProduct:
    return ParsedProduct(
        source=source,
        shop_source_id="shop-test",
        source_product_id="product-test",
        title=title,
        normalized_title=title.lower(),
        fingerprint="fingerprint-test",
        description=None,
        category_raw=None,
        unit_raw=None,
        price=price,
        currency="RUB",
        image_url=None,
        source_updated_at=None,
        raw=raw or {"offer": {"price": 100}},
        parsed_at=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
        price_kind=price_kind,
    )
