import re
from dataclasses import dataclass
from decimal import Decimal

from stroyhub.parsers.common import normalize_title


@dataclass(frozen=True, kw_only=True)
class ExtractedAttribute:
    kind: str
    raw: str
    values: tuple[Decimal, ...] = ()
    unit: str = ""
    normalized: str | None = None
    confidence: Decimal = Decimal("1.000")
    reason: str = "pattern"


@dataclass(frozen=True, kw_only=True)
class ProductAttributeExtraction:
    attributes: tuple[ExtractedAttribute, ...]
    confidence: Decimal
    reasons: tuple[str, ...]


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
_THICKNESS_PATTERN = re.compile(
    rf"(?P<raw>(?:толщ(?:ина)?\.?\s*)?(?P<value>{_NUMBER})\s*(?P<unit>мм|mm)\.?)",
    re.IGNORECASE,
)
_M_GRADE_PATTERN = re.compile(
    r"(?P<raw>(?<![a-zа-яё])[мm]\s*-?\s*\d{2,3}(?![a-zа-яё]))",
    re.IGNORECASE,
)
_OSB_GRADE_PATTERN = re.compile(
    r"(?P<raw>(?:osb|осп|осб)\s*-?\s*(?P<grade>\d))",
    re.IGNORECASE,
)
_PROFILE_SHEET_GRADE_PATTERN = re.compile(
    r"(?P<raw>(?<![a-zа-яё])[сc]\s*-?\s*(?P<grade>\d{1,2})(?![a-zа-яё]))",
    re.IGNORECASE,
)

_TEXT_ATTRIBUTE_ALIASES: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    (
        "product_type",
        "osb",
        ("osb", "осп", "осб", "осп-3", "осб-3", "osb-3"),
        "product_type_alias",
    ),
    ("product_type", "plywood", ("фанера",), "product_type_alias"),
    ("product_type", "drywall", ("гипсокартон", "гкл", "гсп"), "product_type_alias"),
    ("product_type", "cement", ("цемент",), "product_type_alias"),
    ("product_type", "peskobeton", ("пескобетон",), "product_type_alias"),
    (
        "product_type",
        "tile_adhesive",
        ("клей плиточный", "плиточный клей"),
        "product_type_alias",
    ),
    ("product_type", "lumber", ("брус", "доска", "пиломатериал"), "product_type_alias"),
    ("product_type", "profiled_sheet", ("профлист", "профнастил"), "product_type_alias"),
    ("product_type", "brick", ("кирпич",), "product_type_alias"),
    ("brand", "knauf", ("knauf", "кнауф"), "brand_alias"),
    ("brand", "grand_line", ("grand line", "гранд лайн"), "brand_alias"),
    ("brand", "dufa", ("düfa", "dufa", "дюфа"), "brand_alias"),
    ("model", "rotband", ("ротбанд", "rotband"), "model_alias"),
    ("model", "fliesen", ("флизен", "fliesen"), "model_alias"),
    ("model", "amerika_d4", ("amerika d4", "америка d4"), "model_alias"),
    ("model", "gsp_a", ("гсп-а", "gsp-a"), "model_alias"),
    ("model", "gsp_n2", ("гсп-н2", "gsp-n2"), "model_alias"),
    ("material", "pine", ("сосна", "сосновый", "сосновая"), "material_alias"),
    (
        "material",
        "galvanized",
        ("оцинкованный", "оцинкованная", "оцинк"),
        "material_alias",
    ),
    ("material", "acrylic", ("акрил", "акриловый", "акриловая"), "material_alias"),
    ("material", "gypsum", ("гипсовый", "гипсовая", "гипс"), "material_alias"),
)
_SELLING_UNIT_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("m", ("за метр", "за погонный метр", "пог.м", "п.м.")),
    ("m2", ("за м2", "за м²", "за кв.м", "за квадратный метр")),
    ("kg", ("за кг", "за килограмм")),
    ("pcs", ("за шт", "за штуку")),
)
_COMMON_NOISE_PHRASES: tuple[str, ...] = (
    "в ассортименте",
    "под заказ",
)
_SOURCE_NOISE_PHRASES: dict[str, tuple[str, ...]] = {
    "2gis": ("цена указана", "уточняйте"),
    "metalltorg": ("цена указана",),
}


def extract_title_attributes(title: str) -> tuple[ExtractedAttribute, ...]:
    return extract_product_attributes(title).attributes


def extract_product_attributes(
    title: str,
    *,
    source: str | None = None,
    category_raw: str | None = None,
) -> ProductAttributeExtraction:
    matches: list[tuple[int, int, ExtractedAttribute]] = []
    occupied_spans: list[tuple[int, int]] = []
    reasons: list[str] = []

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
                raw=match.group("raw"),
                values=tuple(_decimal(value) for value in values),
                unit=unit,
                confidence=Decimal("1.000"),
                reason="dimension_pattern",
            ),
        )
        if match.group("third") is not None and unit == "mm":
            _append_derived_thickness(matches, match)

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

    _append_single_value_matches(
        matches=matches,
        occupied_spans=occupied_spans,
        pattern=_THICKNESS_PATTERN,
        title=title,
        kind="thickness",
        unit="mm",
        reason="thickness_pattern",
    )

    for match in _LENGTH_PATTERN.finditer(title):
        unit = _normalize_length_unit(match.group("unit"))
        _append_match(
            matches,
            occupied_spans,
            match,
            ExtractedAttribute(
                kind="length",
                raw=match.group("raw"),
                values=(_decimal(match.group("value")),),
                unit=unit,
                confidence=Decimal("0.900"),
                reason="length_pattern",
            ),
        )

    _append_grade_matches(matches, title)
    _append_dictionary_attributes(matches, title)
    _append_selling_unit_attributes(matches, title)

    if not title.strip():
        reasons.append("empty_title")
    if category_raw:
        reasons.append("category_context_available")
    if source:
        reasons.append(f"source:{source}")
    reasons.extend(_noise_reasons(title, source=source))
    if not matches:
        reasons.append("no_attributes_extracted")

    confidence = _extraction_confidence(matches=matches, reasons=reasons)
    return ProductAttributeExtraction(
        attributes=tuple(
            attribute for _, _, attribute in sorted(matches, key=lambda item: item[0])
        ),
        confidence=confidence,
        reasons=tuple(dict.fromkeys(reasons or ["attributes_extracted"])),
    )


def _append_single_value_matches(
    *,
    matches: list[tuple[int, int, ExtractedAttribute]],
    occupied_spans: list[tuple[int, int]],
    pattern: re.Pattern[str],
    title: str,
    kind: str,
    unit: str,
    value_group: str = "value",
    reason: str | None = None,
) -> None:
    for match in pattern.finditer(title):
        _append_match(
            matches,
            occupied_spans,
            match,
            ExtractedAttribute(
                kind=kind,
                raw=match.group("raw"),
                values=(_decimal(match.group(value_group)),),
                unit=unit,
                confidence=Decimal("1.000"),
                reason=reason or f"{kind}_pattern",
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


def _append_derived_thickness(
    matches: list[tuple[int, int, ExtractedAttribute]],
    match: re.Match[str],
) -> None:
    third = match.group("third")
    if third is None:
        return

    raw_end = match.end("third_unit") if match.group("third_unit") else match.end("third")
    matches.append(
        (
            match.start("third"),
            raw_end,
            ExtractedAttribute(
                kind="thickness",
                raw=match.string[match.start("third") : raw_end],
                values=(_decimal(third),),
                unit="mm",
                confidence=Decimal("0.950"),
                reason="dimension_thickness",
            ),
        )
    )


def _append_text_match(
    matches: list[tuple[int, int, ExtractedAttribute]],
    *,
    start: int,
    end: int,
    kind: str,
    raw: str,
    normalized: str,
    confidence: Decimal,
    reason: str,
) -> None:
    existing = {
        (attribute.kind, attribute.normalized)
        for _, _, attribute in matches
        if attribute.normalized is not None
    }
    if (kind, normalized) in existing:
        return

    matches.append(
        (
            start,
            end,
            ExtractedAttribute(
                kind=kind,
                raw=raw,
                normalized=normalized,
                confidence=confidence,
                reason=reason,
            ),
        )
    )


def _append_dictionary_attributes(
    matches: list[tuple[int, int, ExtractedAttribute]],
    title: str,
) -> None:
    normalized_title = normalize_title(title)

    for kind, normalized, aliases, reason in _TEXT_ATTRIBUTE_ALIASES:
        for alias in aliases:
            normalized_alias = normalize_title(alias)
            if not _contains_normalized_phrase(normalized_title, normalized_alias):
                continue

            start, end, raw = _raw_phrase_span(title, alias)
            _append_text_match(
                matches,
                start=start,
                end=end,
                kind=kind,
                raw=raw,
                normalized=normalized,
                confidence=Decimal("0.950"),
                reason=reason,
            )
            break


def _append_grade_matches(matches: list[tuple[int, int, ExtractedAttribute]], title: str) -> None:
    for match in _M_GRADE_PATTERN.finditer(title):
        raw = match.group("raw")
        normalized = re.sub(r"[\s-]+", "", normalize_title(raw)).replace("m", "м")
        _append_text_match(
            matches,
            start=match.start("raw"),
            end=match.end("raw"),
            kind="grade",
            raw=raw,
            normalized=normalized,
            confidence=Decimal("1.000"),
            reason="grade_pattern",
        )

    for match in _OSB_GRADE_PATTERN.finditer(title):
        raw = match.group("raw")
        _append_text_match(
            matches,
            start=match.start("raw"),
            end=match.end("raw"),
            kind="grade",
            raw=raw,
            normalized=f"osb-{match.group('grade')}",
            confidence=Decimal("1.000"),
            reason="grade_pattern",
        )

    for match in _PROFILE_SHEET_GRADE_PATTERN.finditer(title):
        raw = match.group("raw")
        _append_text_match(
            matches,
            start=match.start("raw"),
            end=match.end("raw"),
            kind="grade",
            raw=raw,
            normalized=f"c{match.group('grade')}",
            confidence=Decimal("0.950"),
            reason="grade_pattern",
        )


def _append_selling_unit_attributes(
    matches: list[tuple[int, int, ExtractedAttribute]],
    title: str,
) -> None:
    normalized_title = normalize_title(title)

    for normalized, aliases in _SELLING_UNIT_ALIASES:
        for alias in aliases:
            normalized_alias = normalize_title(alias)
            if not _contains_normalized_phrase(normalized_title, normalized_alias):
                continue

            start, end, raw = _raw_phrase_span(title, alias)
            _append_text_match(
                matches,
                start=start,
                end=end,
                kind="selling_unit",
                raw=raw,
                normalized=normalized,
                confidence=Decimal("0.850"),
                reason="selling_unit_alias",
            )
            break


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


def _contains_normalized_phrase(normalized_title: str, normalized_phrase: str) -> bool:
    if not normalized_phrase:
        return False

    pattern = re.compile(
        rf"(?<![a-zа-яё0-9]){re.escape(normalized_phrase)}(?![a-zа-яё0-9])",
        re.IGNORECASE,
    )
    return bool(pattern.search(normalized_title))


def _raw_phrase_span(title: str, phrase: str) -> tuple[int, int, str]:
    pattern = re.compile(re.escape(phrase), re.IGNORECASE)
    match = pattern.search(title)
    if match is not None:
        return match.start(), match.end(), match.group(0)

    return len(title), len(title), phrase


def _noise_reasons(title: str, *, source: str | None = None) -> tuple[str, ...]:
    normalized_title = normalize_title(title)
    phrases = list(_COMMON_NOISE_PHRASES)
    if source is None:
        for source_phrases in _SOURCE_NOISE_PHRASES.values():
            phrases.extend(source_phrases)
    else:
        phrases.extend(_SOURCE_NOISE_PHRASES.get(normalize_title(source), ()))

    return tuple(
        f"noise:{normalize_title(phrase).replace(' ', '_')}"
        for phrase in phrases
        if _contains_normalized_phrase(normalized_title, normalize_title(phrase))
    )


def _extraction_confidence(
    *,
    matches: list[tuple[int, int, ExtractedAttribute]],
    reasons: list[str],
) -> Decimal:
    score = Decimal("1.000")
    if not matches:
        score -= Decimal("0.500")
    if any(reason.startswith("noise:") for reason in reasons):
        score -= Decimal("0.200")
    if "empty_title" in reasons:
        score -= Decimal("0.300")

    return max(Decimal("0.000"), score).quantize(Decimal("0.001"))
