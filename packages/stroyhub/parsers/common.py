import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

JsonObject = dict[str, Any]


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
