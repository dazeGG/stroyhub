from stroyhub.catalog.categorization import ManualCategoryOverride, RuleBasedCategorizer


def test_rule_based_categorizer_returns_category_and_confidence() -> None:
    prediction = RuleBasedCategorizer().categorize(
        title="Цемент М500 50 кг",
        category_raw="Строительные смеси",
    )

    assert prediction is not None
    assert prediction.category_slug == "cement"
    assert prediction.category_name == "Цемент"
    assert prediction.confidence >= 0.6
    assert prediction.source == "rules"
    assert "цемент" in prediction.matched_keywords


def test_rule_based_categorizer_uses_category_raw_and_title() -> None:
    prediction = RuleBasedCategorizer().categorize(
        title="Кирпич керамический одинарный",
        category_raw="Кирпич, блоки",
    )

    assert prediction is not None
    assert prediction.category_slug == "bricks_blocks"
    assert prediction.confidence > 0.7


def test_rule_based_categorizer_manual_override_takes_precedence() -> None:
    prediction = RuleBasedCategorizer().categorize(
        title="Цемент М500",
        category_raw="Строительные смеси",
        manual_override=ManualCategoryOverride(
            category_slug="aggregates",
            category_name="Песок и щебень",
        ),
    )

    assert prediction is not None
    assert prediction.category_slug == "aggregates"
    assert prediction.category_name == "Песок и щебень"
    assert prediction.confidence == 1.0
    assert prediction.source == "manual_override"
    assert prediction.matched_keywords == ()


def test_rule_based_categorizer_returns_none_for_unmatched_products() -> None:
    prediction = RuleBasedCategorizer().categorize(
        title="Подарочный сертификат",
        category_raw=None,
    )

    assert prediction is None
