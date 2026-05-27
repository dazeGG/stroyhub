from decimal import Decimal

from stroyhub.catalog.eligibility import (
    ProductEligibilityInput,
    evaluate_product_eligibility,
    is_matchable_source_product,
    with_catalog_eligibility,
)


def test_twogis_product_eligibility_rejects_from_price_group_listing() -> None:
    result = evaluate_product_eligibility(
        ProductEligibilityInput(
            source="2gis",
            title="Гвозди",
            price=Decimal("2"),
            raw={"offer": {"price": "от 2 ₽"}},
        )
    )

    assert result.status == "ineligible"
    assert result.is_not_product is True
    assert result.reasons == (
        "non_exact_price",
        "generic_title",
        "no_specific_product_attributes",
    )


def test_twogis_product_eligibility_rejects_title_implied_from_price_listing() -> None:
    result = evaluate_product_eligibility(
        ProductEligibilityInput(
            source="2gis",
            title="Брус от 100 *100 мм до 180*180 мм, длина 6 м",
            price=Decimal("3250"),
            raw={"offer": {"price_value": {"fixed": {"value": 3250, "currency": "RUB"}}}},
        )
    )

    assert result.status == "ineligible"
    assert result.reasons == ("non_exact_price",)


def test_twogis_product_eligibility_allows_specific_product_range_title() -> None:
    result = evaluate_product_eligibility(
        ProductEligibilityInput(
            source="2gis",
            title="Набор инструмента 120 предметов головки от 4 до 50 TSTOP",
            price=Decimal("17300"),
            raw={"offer": {"price_value": {"fixed": {"value": 17300, "currency": "RUB"}}}},
        )
    )

    assert result.status == "eligible"


def test_twogis_product_eligibility_rejects_generic_exact_price_card() -> None:
    result = evaluate_product_eligibility(
        ProductEligibilityInput(
            source="2gis",
            title="Песок мытый",
            price=Decimal("200"),
            raw={"offer": {"price": 200}},
        )
    )

    assert result.status == "ineligible"
    assert result.reasons == ("generic_title", "no_specific_product_attributes")


def test_twogis_product_eligibility_allows_specific_exact_price_card() -> None:
    result = evaluate_product_eligibility(
        ProductEligibilityInput(
            source="2gis",
            title="Гвозди строительные 3,0х70 мм 1кг",
            price=Decimal("180"),
            raw={"offer": {"price": 180}},
        )
    )

    assert result.status == "eligible"
    assert result.is_matchable is True
    assert result.score >= 70


def test_matchable_source_product_requires_eligible_raw_status() -> None:
    result = evaluate_product_eligibility(
        ProductEligibilityInput(
            source="2gis",
            title="Кирпич",
            price=Decimal("300"),
            raw={"offer": {"price": 300}},
        )
    )
    raw = with_catalog_eligibility({"offer": {"price": 300}}, result)

    assert is_matchable_source_product(raw, is_not_product=False) is False
