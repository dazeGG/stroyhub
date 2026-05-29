from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Literal

from stroyhub.catalog.product_suitability import ProductSuitabilityEvaluator
from stroyhub.ml.not_product_classifier import (
    NotProductClassifierModelUnavailableError,
    NotProductClassifierResult,
)
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


def test_product_suitability_compares_patron_threshold_before_rounding() -> None:
    evaluator = ProductSuitabilityEvaluator(
        patron=FakePatron(not_product_probability=0.6996)
    )

    decision = evaluator.evaluate(_product(source="unicom", title="Цемент М500"))

    assert decision.status == "needs_review"
    assert decision.reasons == ("patron_uncertain",)
    assert decision.not_product_probability == Decimal("0.700")


def test_product_suitability_passes_full_patron_feature_record() -> None:
    patron = FakePatron(not_product_probability=0.10)
    evaluator = ProductSuitabilityEvaluator(patron=patron)

    evaluator.evaluate(
        _product(
            source="unicom",
            title="Цемент М500 25 кг",
            raw={"offer": {"price": 500}},
            description="Портландцемент для строительных работ",
            category_raw="Цемент",
            unit_raw="мешок",
        ),
        shop_name="Юником",
        shop_url="https://unicom-ykt.ru/",
        category_name="Цемент",
        category_path=("Сухие смеси", "Цемент"),
    )

    record = patron.records[0]
    assert record["shop"]["name"] == "Юником"
    assert record["shop"]["url"] == "https://unicom-ykt.ru/"
    assert record["product"]["description"] == "Портландцемент для строительных работ"
    assert record["product"]["category_name"] == "Цемент"
    assert record["product"]["category_path"] == ["Сухие смеси", "Цемент"]
    assert record["latest_price"]["price_text"] == "100.00 RUB"


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


def test_product_suitability_can_require_patron_model(tmp_path) -> None:
    try:
        ProductSuitabilityEvaluator.default(root=tmp_path, require_patron=True)
    except NotProductClassifierModelUnavailableError as error:
        assert "Patron model is unavailable" in str(error)
    else:
        raise AssertionError("expected missing Patron model error")


class FakePatron:
    def __init__(self, *, not_product_probability: float, threshold: float = 0.70) -> None:
        self._not_product_probability = not_product_probability
        self._threshold = threshold
        self.calls = 0
        self.records: list[dict[str, Any]] = []

    def predict_record(self, record: dict[str, Any]) -> NotProductClassifierResult:
        self.calls += 1
        self.records.append(record)
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
    description: str | None = None,
    category_raw: str | None = None,
    unit_raw: str | None = None,
) -> ParsedProduct:
    return ParsedProduct(
        source=source,
        shop_source_id="shop-test",
        source_product_id="product-test",
        title=title,
        normalized_title=title.lower(),
        fingerprint="fingerprint-test",
        description=description,
        category_raw=category_raw,
        unit_raw=unit_raw,
        price=price,
        currency="RUB",
        image_url=None,
        source_updated_at=None,
        raw=raw or {"offer": {"price": 100}},
        parsed_at=datetime(2026, 5, 27, 12, 0, tzinfo=UTC),
        price_kind=price_kind,
    )
