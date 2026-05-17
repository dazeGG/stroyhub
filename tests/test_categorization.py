from stroyhub.catalog.categorization import ManualCategoryOverride, RuleBasedCategorizer
from stroyhub.catalog.taxonomy import (
    DEFAULT_NORMALIZED_CATEGORIES,
    get_normalized_category,
    iter_leaf_categories,
    iter_root_categories,
)


def test_rule_based_categorizer_returns_category_and_confidence() -> None:
    prediction = RuleBasedCategorizer().categorize(
        title="Цемент М500 50 кг",
        category_raw="Строительные смеси",
    )

    assert prediction is not None
    assert prediction.category_slug == "cement"
    assert prediction.category_name == "Цемент"
    assert prediction.parent_slug == "mixes_aggregates"
    assert prediction.parent_name == "Смеси и сыпучие материалы"
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


def test_rule_based_categorizer_covers_raw_source_categories() -> None:
    examples = [
        ("Сухая смесь универсальная", "Сухие строительные смеси", "dry_mixes"),
        ("Штукатурка гипсовая", "Сухие строительные смеси", "plaster_mixes"),
        ("Саморез кровельный", "Саморезы кровельные", "roofing_accessories"),
        ("ГКЛ KNAUF 2500х1200", "Гипсокартон и комплектующие", "drywall"),
        ("Труба канализационная 110 мм", "Трубы и фитинги канализационные", "sewer_pipes"),
        ("Кабель ВВГнг 3х2.5", "Кабели и провода", "cables_wires"),
        ("Дверь входная металлическая", "Двери входные и межкомнатные", "doors"),
        ("Профнастил С-8", "Профлист, металлочерепица", "profiled_sheet"),
    ]

    categorizer = RuleBasedCategorizer()
    for title, category_raw, expected_slug in examples:
        prediction = categorizer.categorize(title=title, category_raw=category_raw)

        assert prediction is not None
        assert prediction.category_slug == expected_slug


def test_default_taxonomy_has_parent_categories_before_leaves() -> None:
    seen_slugs: set[str] = set()

    for category in DEFAULT_NORMALIZED_CATEGORIES:
        if category.parent_slug is not None:
            assert category.parent_slug in seen_slugs
        seen_slugs.add(category.slug)


def test_default_taxonomy_exposes_leaf_categories_for_rules() -> None:
    root_slugs = {category.slug for category in iter_root_categories()}
    leaf_slugs = {category.slug for category in iter_leaf_categories()}

    assert "mixes_aggregates" in root_slugs
    assert "cement" in leaf_slugs
    assert len(leaf_slugs) >= 70
    assert root_slugs.isdisjoint(leaf_slugs)
    cement = get_normalized_category("cement")
    assert cement is not None
    assert cement.parent_slug == "mixes_aggregates"
