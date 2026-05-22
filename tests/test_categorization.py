from stroyhub.catalog.categorization import (
    DEFAULT_NON_PRODUCT_SOURCE_CATEGORIES,
    DEFAULT_SOURCE_CATEGORY_ALIASES,
    ManualCategoryOverride,
    NonProductSourceCategory,
    RuleBasedCategorizer,
    SourceCategoryAlias,
)
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


def test_rule_based_categorizer_source_category_alias_takes_precedence() -> None:
    prediction = RuleBasedCategorizer().categorize(
        title="Цемент М500 50 кг",
        category_raw="Профлист, металлочерепица",
        source="2gis",
    )

    assert prediction is not None
    assert prediction.category_slug == "profiled_sheet"
    assert prediction.category_name == "Профлист и металлочерепица"
    assert prediction.parent_slug == "roofing_facade"
    assert prediction.confidence == 0.98
    assert prediction.source == "source_category_alias"
    assert prediction.matched_keywords == ("Профлист, металлочерепица",)


def test_rule_based_categorizer_alias_requires_matching_source() -> None:
    categorizer = RuleBasedCategorizer(
        rules=(),
        source_category_aliases=(
            SourceCategoryAlias(
                source="2gis",
                raw_category="Профлист, металлочерепица",
                category_slug="profiled_sheet",
            ),
        ),
    )

    prediction = categorizer.categorize(
        title="Без сильных ключевых слов",
        category_raw="Профлист, металлочерепица",
        source="unknown",
    )

    assert prediction is None


def test_rule_based_categorizer_aliases_cover_known_sources() -> None:
    examples = [
        ("2gis", "Гипсокартон и комплектующие", "drywall"),
        ("unicom", "Сухие клеевые смеси", "tile_adhesives"),
        ("metalltorg", "Кирпич", "bricks_blocks"),
    ]

    categorizer = RuleBasedCategorizer()
    for source, category_raw, expected_slug in examples:
        prediction = categorizer.categorize(
            title="Без сильных ключевых слов",
            category_raw=category_raw,
            source=source,
        )

        assert prediction is not None
        assert prediction.category_slug == expected_slug
        assert prediction.source == "source_category_alias"


def test_default_source_category_aliases_point_to_known_categories() -> None:
    for alias in DEFAULT_SOURCE_CATEGORY_ALIASES:
        assert get_normalized_category(alias.category_slug) is not None


def test_rule_based_categorizer_leaves_non_product_work_cards_uncategorized() -> None:
    categorizer = RuleBasedCategorizer()
    examples = [
        "Кладовщик",
        "Продавец-консультант",
        "Инструмент строительный",
    ]

    for title in examples:
        prediction = categorizer.categorize(
            title=title,
            source="2gis",
            category_raw="Работа",
        )

        assert prediction is None


def test_rule_based_categorizer_non_product_categories_can_be_customized() -> None:
    categorizer = RuleBasedCategorizer(
        non_product_source_categories=(
            NonProductSourceCategory(source="example", raw_category="Services"),
        ),
    )

    prediction = categorizer.categorize(
        title="Краскопульт",
        source="2gis",
        category_raw="Материалы",
    )

    assert prediction is not None
    assert prediction.category_slug == "painting_plastering_tools"


def test_default_non_product_source_categories_are_normalized() -> None:
    assert DEFAULT_NON_PRODUCT_SOURCE_CATEGORIES

    categorizer = RuleBasedCategorizer()
    prediction = categorizer.categorize(
        title="Инструмент строительный",
        source=" 2GIS ",
        category_raw=" работа ",
    )

    assert prediction is None


def test_rule_based_categorizer_returns_none_for_unmatched_products() -> None:
    prediction = RuleBasedCategorizer().categorize(
        title="Подарочный сертификат",
        category_raw=None,
    )

    assert prediction is None


def test_rule_based_categorizer_does_not_match_short_keyword_inside_word() -> None:
    prediction = RuleBasedCategorizer().categorize(
        title="Шлакоблок полнотелый",
        category_raw=None,
    )

    assert prediction is None


def test_rule_based_categorizer_does_not_match_keyword_inside_prefix_word() -> None:
    prediction = RuleBasedCategorizer().categorize(
        title="Наклейка декоративная",
        category_raw=None,
    )

    assert prediction is None


def test_rule_based_categorizer_still_matches_single_token_keyword() -> None:
    prediction = RuleBasedCategorizer().categorize(
        title="Клей монтажный универсальный",
        category_raw=None,
    )

    assert prediction is not None
    assert prediction.category_slug == "construction_adhesives"
    assert "клей" in prediction.matched_keywords


def test_rule_based_categorizer_still_matches_multi_word_phrase() -> None:
    prediction = RuleBasedCategorizer().categorize(
        title="Сухая смесь универсальная 25 кг",
        category_raw=None,
    )

    assert prediction is not None
    assert prediction.category_slug == "dry_mixes"
    assert "сухая смесь" in prediction.matched_keywords


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


def test_rule_based_categorizer_covers_insulation_audit_examples() -> None:
    examples = [
        (
            "ISOVER СТАНДАРТ (600*1000*50) 0,24 куб. 4,8 кв.м.(8 плит)",
            "Утеплители",
            "mineral_wool",
        ),
        (
            "ТЕХНОБЛОК СТАНДАРТ (1200*600*50)",
            "Утеплители",
            "mineral_wool",
        ),
        (
            "Утеплитель ТехноТерм TR 040 Aquastatik 7,214*1,22*0,05 2 шт S-17.602м2",
            "Утеплители",
            "mineral_wool",
        ),
        (
            "КНАУФ ТИСМА Aquastatic (рулон)(1,2 х16.6м) 19,9 кв.м/0,996 куб.м",
            "Утеплители",
            "mineral_wool",
        ),
        (
            "Межвенцовый утеплитель ЭКОСТЕН Sintex ПЭ 100мм*20м",
            "Утеплитель межвенцовый",
            "natural_fiber_insulation",
        ),
        (
            "Пакля джутовая 10 кг/тюк",
            "Утеплитель межвенцовый",
            "natural_fiber_insulation",
        ),
    ]

    categorizer = RuleBasedCategorizer()
    for title, category_raw, expected_slug in examples:
        prediction = categorizer.categorize(
            title=title,
            source="2gis",
            category_raw=category_raw,
        )

        assert prediction is not None
        assert prediction.category_slug == expected_slug


def test_rule_based_categorizer_covers_sip_panel_audit_examples() -> None:
    examples = [
        "Панель 1250*2500*109 (0/9) потолочный",
        "Панель 1250*2500*118 (9/9)",
        "Панель 1250*2500*174 (12/12)",
    ]

    categorizer = RuleBasedCategorizer()
    for title in examples:
        prediction = categorizer.categorize(
            title=title,
            source="2gis",
            category_raw="СИП ПАНЕЛИ",
        )

        assert prediction is not None
        assert prediction.category_slug == "sip_panels"
        assert prediction.category_name == "СИП-панели"
        assert prediction.parent_slug == "sheet_board_materials"
        assert prediction.source == "source_category_alias"


def test_rule_based_categorizer_handles_generic_materials_by_title_signal() -> None:
    examples = [
        ("Звонки электрические", "wiring_devices"),
        ("Инструмент строительный", "hand_tools"),
        ("Краскопульт", "painting_plastering_tools"),
        ('Потолок подвесной "Оазис" Байкал,Ритейл 600*600*12мм', "ceilings"),
    ]

    categorizer = RuleBasedCategorizer()
    for title, expected_slug in examples:
        prediction = categorizer.categorize(
            title=title,
            source="2gis",
            category_raw="Материалы",
        )

        assert prediction is not None
        assert prediction.category_slug == expected_slug
        assert prediction.source == "rules"


def test_rule_based_categorizer_handles_special_purpose_by_title_signal() -> None:
    examples = [
        "Покрытие финиш. полиур. д\\пола Graspolimer 20м2",
        "Пол налив. полиурет. DGENERX FR 111 30кг",
    ]

    categorizer = RuleBasedCategorizer()
    for title in examples:
        prediction = categorizer.categorize(
            title=title,
            source="2gis",
            category_raw="Специального назначения",
        )

        assert prediction is not None
        assert prediction.category_slug == "floor_mixes"
        assert prediction.source == "rules"


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
