import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Literal

JsonObject = dict[str, Any]
PriceKind = Literal["exact", "from", "range", "unknown"]
_CATALOG_RANGE_TITLE_PREFIXES = frozenset(
    {
        "арматура",
        "брус",
        "доска",
        "лист",
        "пиловочник",
        "полоса",
        "профиль",
        "труба",
        "уголок",
        "фанера",
        "швеллер",
    }
)


@dataclass(frozen=True, kw_only=True)
class ParsedProduct:
    source: str
    shop_source_id: str
    title: str
    normalized_title: str
    source_product_id: str | None
    fingerprint: str | None
    description: str | None
    category_raw: str | None
    unit_raw: str | None
    price: Decimal | None
    currency: str
    image_url: str | None
    source_updated_at: datetime | None
    raw: JsonObject
    parsed_at: datetime
    price_kind: PriceKind = "exact"


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.casefold()).strip()


def build_fingerprint(*parts: str | None) -> str | None:
    normalized_parts = [normalize_title(part) for part in parts if part and part.strip()]
    if not normalized_parts:
        return None

    payload = "\x1f".join(normalized_parts)
    return sha256(payload.encode("utf-8")).hexdigest()


def parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None

    if isinstance(value, Decimal):
        return value

    if isinstance(value, int):
        return Decimal(value)

    if isinstance(value, float):
        return Decimal(str(value))

    if not isinstance(value, str):
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    cleaned = cleaned.replace("\xa0", " ")
    cleaned = re.sub(r"[^\d,.\-]", "", cleaned)
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(" ", "").replace(",", "")
    else:
        cleaned = cleaned.replace(" ", "").replace(",", ".")

    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def infer_price_kind(
    *,
    title: str,
    price: Decimal | None,
    raw_kind: PriceKind | None = None,
) -> PriceKind:
    if raw_kind in {"from", "range"}:
        return raw_kind
    if price is None:
        return "unknown"
    if title_implies_from_price(title):
        return "from"
    return raw_kind or "exact"


def title_implies_from_price(title: str) -> bool:
    normalized = normalize_title(title)
    words = re.findall(r"[0-9a-zа-яё]+", normalized, flags=re.IGNORECASE)
    if not words or words[0] not in _CATALOG_RANGE_TITLE_PREFIXES:
        return False

    patterns = (
        r"(?<!\w)от(?!\w).{0,120}(?<!\w)до(?!\w)",
        r"(?<!\w)от\s*\d",
        r"(?<!\w)и\s+более(?!\w)",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)
