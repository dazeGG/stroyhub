from datetime import UTC, datetime
from decimal import Decimal

from stroyhub.parsers.common import (
    JsonObject,
    ParsedProduct,
    PriceKind,
    build_fingerprint,
    infer_price_kind,
    normalize_title,
    parse_decimal,
)

TWOGIS_SOURCE = "2gis"

MONTHS_RU = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def parse_product_items(
    items: list[JsonObject],
    *,
    branch_id: str,
    source_updated_at_raw: str | None = None,
    parsed_at: datetime | None = None,
) -> list[ParsedProduct]:
    return [
        parsed
        for item in items
        if (
            parsed := parse_product_item(
                item,
                branch_id=branch_id,
                source_updated_at_raw=source_updated_at_raw,
                parsed_at=parsed_at,
            )
        )
        is not None
    ]


def parse_product_item(
    item: JsonObject,
    *,
    branch_id: str,
    source_updated_at_raw: str | None = None,
    parsed_at: datetime | None = None,
) -> ParsedProduct | None:
    product = item.get("product")
    if not isinstance(product, dict):
        return None

    title = _string_or_none(product.get("name"))
    if title is None:
        return None

    offer = item.get("offer")
    if not isinstance(offer, dict):
        offer = {}

    normalized_title = normalize_title(title)
    source_product_id = _string_or_none(product.get("id"))
    category_raw = _category_raw(product)
    unit_raw = _unit_raw(item)
    price = _price(offer)
    raw_price_kind = _raw_price_kind(offer)
    currency = _string_or_none(offer.get("currency")) or _currency_from_price_value(offer) or "RUB"

    return ParsedProduct(
        source=TWOGIS_SOURCE,
        shop_source_id=branch_id,
        source_product_id=source_product_id,
        title=title,
        normalized_title=normalized_title,
        description=_empty_to_none(_string_or_none(product.get("description"))),
        category_raw=category_raw,
        unit_raw=unit_raw,
        price=price,
        price_kind=infer_price_kind(title=title, price=price, raw_kind=raw_price_kind),
        currency=currency,
        image_url=_first_string(product.get("images")),
        source_updated_at=parse_source_updated_at(source_updated_at_raw),
        fingerprint=build_fingerprint(normalized_title, unit_raw, category_raw),
        raw=item,
        parsed_at=parsed_at or datetime.now(UTC),
    )


def parse_source_updated_at(value: str | None) -> datetime | None:
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    parsed: datetime | None
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        parsed = _parse_russian_updated_at(cleaned)

    if parsed is None:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_russian_updated_at(value: str) -> datetime | None:
    parts = value.replace("Обновлено", "").strip().split()
    if len(parts) != 3:
        return None

    day_raw, month_raw, year_raw = parts
    try:
        day = int(day_raw)
        year = int(year_raw)
    except ValueError:
        return None

    month = MONTHS_RU.get(month_raw.casefold())
    if month is None:
        return None

    return datetime(year, month, day)


def _price(offer: JsonObject) -> Decimal | None:
    price = parse_decimal(offer.get("price"))
    if price is not None:
        return price

    price_value = offer.get("price_value")
    if not isinstance(price_value, dict):
        return None

    fixed = price_value.get("fixed")
    if isinstance(fixed, dict):
        return parse_decimal(fixed.get("value"))

    from_price = price_value.get("from")
    if not isinstance(from_price, dict):
        return None

    return parse_decimal(from_price.get("value"))


def _raw_price_kind(offer: JsonObject) -> PriceKind | None:
    price_value = offer.get("price_value")
    if not isinstance(price_value, dict):
        return None
    if isinstance(price_value.get("from"), dict):
        return "from"
    if isinstance(price_value.get("fixed"), dict) or offer.get("price") is not None:
        return "exact"
    if isinstance(price_value.get("empty"), dict):
        return "unknown"
    return None


def _currency_from_price_value(offer: JsonObject) -> str | None:
    price_value = offer.get("price_value")
    if not isinstance(price_value, dict):
        return None

    fixed = price_value.get("fixed")
    if isinstance(fixed, dict):
        return _string_or_none(fixed.get("currency"))

    from_price = price_value.get("from")
    if isinstance(from_price, dict):
        return _string_or_none(from_price.get("currency"))

    return None


def _category_raw(product: JsonObject) -> str | None:
    labels = []
    categories = product.get("categories")
    if isinstance(categories, list):
        for category in categories:
            if isinstance(category, dict):
                label = _string_or_none(category.get("label"))
                if label is not None:
                    labels.append(label)

    if labels:
        return " / ".join(labels)

    blocking_attributes = product.get("blocking_attributes")
    if isinstance(blocking_attributes, list):
        for attribute in blocking_attributes:
            if isinstance(attribute, dict):
                caption = _string_or_none(attribute.get("caption"))
                if caption is not None:
                    return caption

    return None


def _unit_raw(item: JsonObject) -> str | None:
    return _find_string_by_key_fragment(item, ("unit", "measure"))


def _find_string_by_key_fragment(value: object, fragments: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if any(fragment in key.casefold() for fragment in fragments):
                found = _string_or_none(nested_value)
                if found is not None:
                    return found
            nested = _find_string_by_key_fragment(nested_value, fragments)
            if nested is not None:
                return nested

    if isinstance(value, list):
        for nested_value in value:
            nested = _find_string_by_key_fragment(nested_value, fragments)
            if nested is not None:
                return nested

    return None


def _first_string(value: object) -> str | None:
    if not isinstance(value, list):
        return None

    for item in value:
        if isinstance(item, str) and item.strip():
            return item

    return None


def _string_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    return cleaned


def _empty_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value
