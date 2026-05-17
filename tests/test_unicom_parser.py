import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from stroyhub.parsers.unicom import parse_created_date, parse_product, parse_products

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "unicom"


def _load_products() -> list[dict[str, object]]:
    payload = json.loads((FIXTURES_DIR / "products-cement-page1.json").read_text())
    products = payload["products"]
    assert isinstance(products, list)
    return [product for product in products if isinstance(product, dict)]


def test_parse_product_maps_unicom_fields_to_parsed_product() -> None:
    parsed_at = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    raw_product = _load_products()[0]

    parsed = parse_product(
        raw_product,
        shop_source_id="uc",
        parsed_at=parsed_at,
    )

    assert parsed is not None
    assert parsed.source == "unicom"
    assert parsed.shop_source_id == "uc"
    assert parsed.source_product_id == "7bc6787cedca11e682177062b8b53ba3"
    assert parsed.title == "Цемент М-400 50кг."
    assert parsed.normalized_title == "цемент м-400 50кг."
    assert parsed.description is None
    assert parsed.category_raw == "Цемент"
    assert parsed.unit_raw == "шт."
    assert parsed.price == Decimal("958.00")
    assert parsed.currency == "RUB"
    assert parsed.image_url is None
    assert parsed.source_updated_at is None
    assert parsed.fingerprint is not None
    assert parsed.raw == raw_product
    assert parsed.parsed_at == parsed_at


def test_parse_product_maps_created_date_when_available() -> None:
    raw_product = _load_products()[1]

    parsed = parse_product(raw_product)

    assert parsed is not None
    assert parsed.source_updated_at == datetime(2022, 12, 9, 23, 10, 25, tzinfo=UTC)


def test_parse_product_handles_missing_optional_fields_and_bad_price() -> None:
    parsed = parse_product(
        {
            "name": "Товар без цены",
            "uuid": "",
            "category": "",
            "price": "по запросу",
            "price_unit": "",
            "created_date": "bad",
        }
    )

    assert parsed is not None
    assert parsed.source_product_id is None
    assert parsed.category_raw is None
    assert parsed.unit_raw is None
    assert parsed.price is None
    assert parsed.source_updated_at is None
    assert parsed.fingerprint is not None


def test_parse_product_skips_products_without_title() -> None:
    assert parse_product({"uuid": "product-1"}) is None
    assert parse_products([{"name": "Цемент"}, {"uuid": "missing-title"}])[0].title == "Цемент"


def test_parse_created_date_handles_unix_timestamp_strings_and_invalid_values() -> None:
    assert parse_created_date("1670627425") == datetime(
        2022,
        12,
        9,
        23,
        10,
        25,
        tzinfo=UTC,
    )
    assert parse_created_date(1670627425) == datetime(2022, 12, 9, 23, 10, 25, tzinfo=UTC)
    assert parse_created_date(None) is None
    assert parse_created_date("1670.5") is None
    assert parse_created_date("bad") is None
