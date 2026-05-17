from datetime import UTC, datetime

from stroyhub.parsers.common import (
    JsonObject,
    ParsedProduct,
    build_fingerprint,
    normalize_title,
    parse_decimal,
)

UNICOM_SOURCE = "unicom"
UNICOM_DEFAULT_SHOP_SOURCE_ID = "uc"
UNICOM_DEFAULT_CURRENCY = "RUB"


def parse_products(
    products: list[JsonObject],
    *,
    shop_source_id: str = UNICOM_DEFAULT_SHOP_SOURCE_ID,
    parsed_at: datetime | None = None,
) -> list[ParsedProduct]:
    return [
        parsed
        for product in products
        if (
            parsed := parse_product(
                product,
                shop_source_id=shop_source_id,
                parsed_at=parsed_at,
            )
        )
        is not None
    ]


def parse_product(
    product: JsonObject,
    *,
    shop_source_id: str = UNICOM_DEFAULT_SHOP_SOURCE_ID,
    parsed_at: datetime | None = None,
) -> ParsedProduct | None:
    title = _string_or_none(product.get("name"))
    if title is None:
        return None

    normalized_title = normalize_title(title)
    category_raw = _string_or_none(product.get("category"))
    unit_raw = _string_or_none(product.get("price_unit"))

    return ParsedProduct(
        source=UNICOM_SOURCE,
        shop_source_id=shop_source_id,
        source_product_id=_string_or_none(product.get("uuid")),
        title=title,
        normalized_title=normalized_title,
        description=None,
        category_raw=category_raw,
        unit_raw=unit_raw,
        price=parse_decimal(product.get("price")),
        currency=UNICOM_DEFAULT_CURRENCY,
        image_url=None,
        source_updated_at=parse_created_date(product.get("created_date")),
        fingerprint=build_fingerprint(normalized_title, unit_raw, category_raw),
        raw=product,
        parsed_at=parsed_at or datetime.now(UTC),
    )


def parse_created_date(value: object) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, int):
        timestamp = value
    elif isinstance(value, str) and value.isdecimal():
        timestamp = int(value)
    else:
        return None

    try:
        return datetime.fromtimestamp(timestamp, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


def _string_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    return cleaned
