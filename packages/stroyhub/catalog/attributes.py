import re
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, kw_only=True)
class ExtractedAttribute:
    kind: str
    values: tuple[Decimal, ...]
    unit: str
    raw: str


_NUMBER = r"\d+(?:[,.]\d+)?"
_DIMENSION_UNIT = r"(?:мм|mm|м|m)"
_DIMENSION_PATTERN = re.compile(
    rf"(?P<raw>"
    rf"(?P<first>{_NUMBER})\s*(?P<first_unit>{_DIMENSION_UNIT})?\s*"
    rf"[xх*×]\s*"
    rf"(?P<second>{_NUMBER})\s*(?P<second_unit>{_DIMENSION_UNIT})?"
    rf"(?:\s*[xх*×]\s*(?P<third>{_NUMBER})\s*(?P<third_unit>{_DIMENSION_UNIT})?)?"
    rf")",
    re.IGNORECASE,
)
_PACKAGE_PATTERN = re.compile(
    rf"(?P<raw>(?P<count>{_NUMBER})\s*(?:шт|штук|pcs)\.?\s*(?:упак|упаковк\w*))",
    re.IGNORECASE,
)
_WEIGHT_PATTERN = re.compile(rf"(?P<raw>(?P<value>{_NUMBER})\s*(?:кг|kg)\.?)", re.IGNORECASE)
_LITER_PATTERN = re.compile(rf"(?P<raw>(?P<value>{_NUMBER})\s*(?:л|l|литр\w*)\.?)", re.IGNORECASE)
_CUBIC_METER_PATTERN = re.compile(
    rf"(?P<raw>(?P<value>{_NUMBER})\s*(?:м3|м³|m3|куб\.?\s*м\.?))",
    re.IGNORECASE,
)
_AREA_PATTERN = re.compile(
    rf"(?P<raw>(?P<value>{_NUMBER})\s*(?:м2|м²|m2|кв\.?\s*м\.?))",
    re.IGNORECASE,
)
_LENGTH_PATTERN = re.compile(
    rf"(?P<raw>(?P<value>{_NUMBER})\s*(?P<unit>мм|mm|м|m)\.?)",
    re.IGNORECASE,
)


def extract_title_attributes(title: str) -> tuple[ExtractedAttribute, ...]:
    matches: list[tuple[int, int, ExtractedAttribute]] = []
    occupied_spans: list[tuple[int, int]] = []

    for match in _DIMENSION_PATTERN.finditer(title):
        unit = _dimension_unit(match)
        if unit is None:
            continue

        values = [match.group("first"), match.group("second")]
        if match.group("third") is not None:
            values.append(match.group("third"))

        _append_match(
            matches,
            occupied_spans,
            match,
            ExtractedAttribute(
                kind="dimension",
                values=tuple(_decimal(value) for value in values),
                unit=unit,
                raw=match.group("raw"),
            ),
        )

    _append_single_value_matches(
        matches=matches,
        occupied_spans=occupied_spans,
        pattern=_PACKAGE_PATTERN,
        title=title,
        kind="package_count",
        unit="pcs",
        value_group="count",
    )
    _append_single_value_matches(
        matches=matches,
        occupied_spans=occupied_spans,
        pattern=_WEIGHT_PATTERN,
        title=title,
        kind="weight",
        unit="kg",
    )
    _append_single_value_matches(
        matches=matches,
        occupied_spans=occupied_spans,
        pattern=_LITER_PATTERN,
        title=title,
        kind="volume",
        unit="l",
    )
    _append_single_value_matches(
        matches=matches,
        occupied_spans=occupied_spans,
        pattern=_CUBIC_METER_PATTERN,
        title=title,
        kind="volume",
        unit="m3",
    )
    _append_single_value_matches(
        matches=matches,
        occupied_spans=occupied_spans,
        pattern=_AREA_PATTERN,
        title=title,
        kind="area",
        unit="m2",
    )

    for match in _LENGTH_PATTERN.finditer(title):
        unit = _normalize_length_unit(match.group("unit"))
        _append_match(
            matches,
            occupied_spans,
            match,
            ExtractedAttribute(
                kind="length",
                values=(_decimal(match.group("value")),),
                unit=unit,
                raw=match.group("raw"),
            ),
        )

    return tuple(attribute for _, _, attribute in sorted(matches, key=lambda item: item[0]))


def _append_single_value_matches(
    *,
    matches: list[tuple[int, int, ExtractedAttribute]],
    occupied_spans: list[tuple[int, int]],
    pattern: re.Pattern[str],
    title: str,
    kind: str,
    unit: str,
    value_group: str = "value",
) -> None:
    for match in pattern.finditer(title):
        _append_match(
            matches,
            occupied_spans,
            match,
            ExtractedAttribute(
                kind=kind,
                values=(_decimal(match.group(value_group)),),
                unit=unit,
                raw=match.group("raw"),
            ),
        )


def _append_match(
    matches: list[tuple[int, int, ExtractedAttribute]],
    occupied_spans: list[tuple[int, int]],
    match: re.Match[str],
    attribute: ExtractedAttribute,
) -> None:
    span = match.span("raw")
    if _overlaps(span, occupied_spans):
        return
    matches.append((span[0], span[1], attribute))
    occupied_spans.append(span)


def _overlaps(span: tuple[int, int], occupied_spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(
        start < occupied_end and occupied_start < end
        for occupied_start, occupied_end in occupied_spans
    )


def _dimension_unit(match: re.Match[str]) -> str | None:
    raw_unit = match.group("third_unit") or match.group("second_unit") or match.group("first_unit")
    if raw_unit is None:
        return None
    return _normalize_length_unit(raw_unit)


def _normalize_length_unit(unit: str) -> str:
    normalized = unit.casefold().replace("м", "m")
    return "mm" if normalized == "mm" else "m"


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", "."))
