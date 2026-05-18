from stroyhub.catalog.tokenization import tokenize_title
from stroyhub.parsers.common import normalize_title


def test_tokenize_title_handles_russian_and_latin_brand_text() -> None:
    tokens = tokenize_title("Клей плиточный КНАУФ-Флизен GL")

    assert tokens.tokens == ("клей", "плиточный", "кнауф", "флизен", "gl")
    assert tokens.protected_tokens == ()


def test_tokenize_title_preserves_dimension_tokens() -> None:
    tokens = tokenize_title("ГКЛ KNAUF 2500мм*1200мм*9,5мм")

    assert tokens.tokens == ("гкл", "knauf", "2500мм", "1200мм", "9.5мм")
    assert tokens.protected_tokens == ("2500мм", "1200мм", "9.5мм")


def test_tokenize_title_preserves_grade_tokens() -> None:
    tokens = tokenize_title("Цемент М-500 50 кг")

    assert tokens.tokens == ("цемент", "м500", "50кг")
    assert tokens.protected_tokens == ("м500", "50кг")


def test_tokenize_title_preserves_packaging_tokens() -> None:
    tokens = tokenize_title("Сайдинг 238х3000мм (22шт. упак)")

    assert tokens.tokens == ("сайдинг", "238", "3000мм", "22шт", "упак")
    assert tokens.protected_tokens == ("238", "3000мм", "22шт")


def test_normalize_title_behavior_is_preserved() -> None:
    assert normalize_title("  Цемент   М500  ") == "цемент м500"
