from datetime import UTC, datetime
from decimal import Decimal

from stroyhub.parsers.common import build_fingerprint, normalize_title, parse_decimal
from stroyhub.parsers.twogis.parser import parse_product_item, parse_product_items


def test_parse_product_item_maps_2gis_fields_to_parsed_product() -> None:
    parsed_at = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    raw_item = {
        "product": {
            "id": "70266203255300124",
            "name": "Сайдинг 3.0 GL Amerika",
            "description": "Фасадная панель",
            "images": ["https://example.test/image.jpg?h={height}&w={width}"],
            "categories": [{"id": "cat-1", "label": "Сайдинг, фасадные панели"}],
            "attributes": [],
            "blocking_attributes": [{"caption": "Fallback category"}],
        },
        "offer": {
            "price": 515,
            "currency": "RUB",
            "price_value": {"fixed": {"value": 515, "currency": "RUB"}},
        },
    }

    parsed = parse_product_item(
        raw_item,
        branch_id="70000001007229923",
        source_updated_at_raw="Обновлено 13 января 2026",
        parsed_at=parsed_at,
    )

    assert parsed is not None
    assert parsed.source == "2gis"
    assert parsed.shop_source_id == "70000001007229923"
    assert parsed.source_product_id == "70266203255300124"
    assert parsed.title == "Сайдинг 3.0 GL Amerika"
    assert parsed.normalized_title == "сайдинг 3.0 gl amerika"
    assert parsed.description == "Фасадная панель"
    assert parsed.category_raw == "Сайдинг, фасадные панели"
    assert parsed.price == Decimal("515")
    assert parsed.price_kind == "exact"
    assert parsed.currency == "RUB"
    assert parsed.unit_raw is None
    assert parsed.image_url == "https://example.test/image.jpg?h={height}&w={width}"
    assert parsed.source_updated_at == datetime(2026, 1, 13, tzinfo=UTC)
    assert parsed.parsed_at == parsed_at
    assert parsed.raw == raw_item


def test_parse_product_item_handles_missing_optional_fields_and_empty_price() -> None:
    raw_item = {
        "product": {
            "name": "Панель 1250*2500*118",
            "description": "",
            "blocking_attributes": [{"caption": "СИП ПАНЕЛИ"}],
        },
        "offer": {"price_value": {"empty": {}}},
    }

    parsed = parse_product_item(raw_item, branch_id="branch-1")

    assert parsed is not None
    assert parsed.source_product_id is None
    assert parsed.description is None
    assert parsed.category_raw == "СИП ПАНЕЛИ"
    assert parsed.price is None
    assert parsed.price_kind == "unknown"
    assert parsed.currency == "RUB"
    assert parsed.fingerprint is not None


def test_parse_product_item_uses_fixed_price_value_when_offer_price_is_missing() -> None:
    parsed = parse_product_item(
        {
            "product": {"id": "product-1", "name": "Плита OSB"},
            "offer": {"price_value": {"fixed": {"value": "1 550,50", "currency": "RUB"}}},
        },
        branch_id="branch-1",
    )

    assert parsed is not None
    assert parsed.price == Decimal("1550.50")
    assert parsed.price_kind == "exact"
    assert parsed.currency == "RUB"


def test_parse_product_item_preserves_from_price_value() -> None:
    parsed = parse_product_item(
        {
            "product": {"id": "product-1", "name": "Брус"},
            "offer": {"price_value": {"from": {"value": "29 000", "currency": "RUB"}}},
        },
        branch_id="branch-1",
    )

    assert parsed is not None
    assert parsed.price == Decimal("29000")
    assert parsed.price_kind == "from"
    assert parsed.currency == "RUB"


def test_parse_product_item_marks_text_price_from_as_from() -> None:
    parsed = parse_product_item(
        {
            "product": {"id": "product-1", "name": "Доска обрезная"},
            "offer": {"price": "от 29 000 ₽", "currency": "RUB"},
        },
        branch_id="branch-1",
    )

    assert parsed is not None
    assert parsed.price == Decimal("29000")
    assert parsed.price_kind == "from"
    assert parsed.currency == "RUB"


def test_parse_product_item_marks_range_title_price_as_from() -> None:
    parsed = parse_product_item(
        {
            "product": {"id": "product-1", "name": "Брус от 100х100 мм до 180х180 мм"},
            "offer": {"price": 29000, "currency": "RUB"},
        },
        branch_id="branch-1",
    )

    assert parsed is not None
    assert parsed.price == Decimal("29000")
    assert parsed.price_kind == "from"


def test_parse_product_item_keeps_specific_product_title_range_exact() -> None:
    parsed = parse_product_item(
        {
            "product": {
                "id": "product-6",
                "name": "Набор инструмента 120 предметов головки от 4 до 50 TSTOP",
            },
            "offer": {"price_value": {"fixed": {"value": "17300", "currency": "RUB"}}},
        },
        branch_id="branch-1",
    )

    assert parsed is not None
    assert parsed.price == Decimal("17300")
    assert parsed.price_kind == "exact"


def test_parse_product_items_skips_items_without_product_title() -> None:
    parsed = parse_product_items(
        [
            {"product": {"id": "ok", "name": "Цемент"}},
            {"product": {"id": "missing-name"}},
            {"offer": {"price": 100}},
        ],
        branch_id="branch-1",
    )

    assert [item.title for item in parsed] == ["Цемент"]


def test_common_normalization_and_decimal_helpers() -> None:
    assert normalize_title("  Цемент   М500  ") == "цемент м500"
    assert parse_decimal("1 234,50 ₽") == Decimal("1234.50")
    assert build_fingerprint("Цемент М500", "мешок") == build_fingerprint(" цемент  м500 ", "МЕШОК")
