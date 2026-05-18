import re
from dataclasses import dataclass

from stroyhub.parsers.common import normalize_title


@dataclass(frozen=True, kw_only=True)
class TitleTokens:
    tokens: tuple[str, ...]
    protected_tokens: tuple[str, ...]


_TOKEN_PATTERN = re.compile(
    r"""
    \d+(?:[,.]\d+)?\s*(?:кв\.?\s*м\.?|куб\.?\s*м\.?|кг|kg|мм|mm|м2|м²|m2|м3|м³|m3|м|m|л|l|шт|штук|pcs)\.?
    |[a-zа-яё]+\s*-\s*\d+
    |\d+\s*-\s*[a-zа-яё]+
    |[a-zа-яё]+\d+
    |\d+[a-zа-яё]+
    |[a-zа-яё]+
    |\d+(?:[,.]\d+)?
    """,
    re.IGNORECASE | re.VERBOSE,
)


def tokenize_title(title: str) -> TitleTokens:
    tokens = tokenize_normalized_text(normalize_title(title))
    return TitleTokens(
        tokens=tokens,
        protected_tokens=tuple(token for token in tokens if any(char.isdigit() for char in token)),
    )


def tokenize_normalized_text(text: str) -> tuple[str, ...]:
    return tuple(_normalize_token(match.group(0)) for match in _TOKEN_PATTERN.finditer(text))


def _normalize_token(token: str) -> str:
    normalized = token.casefold().strip().replace(" ", "").replace("-", "")
    normalized = re.sub(r"(?<=\d),(?=\d)", ".", normalized)
    normalized = normalized.rstrip(".")
    normalized = re.sub(r"(?<=\d)[xх]$", "", normalized)

    if not any(char.isdigit() for char in normalized):
        return normalized

    normalized = normalized.replace("кв.м", "м2").replace("квм", "м2").replace("м²", "м2")
    normalized = normalized.replace("куб.м", "м3").replace("кубм", "м3").replace("м³", "м3")

    unit_replacements = (
        ("штук", "шт"),
        ("pcs", "шт"),
        ("kg", "кг"),
        ("mm", "мм"),
        ("m2", "м2"),
        ("m3", "м3"),
        ("l", "л"),
        ("m", "м"),
    )
    for suffix, replacement in unit_replacements:
        if normalized.endswith(suffix):
            return f"{normalized[: -len(suffix)]}{replacement}"

    return normalized
