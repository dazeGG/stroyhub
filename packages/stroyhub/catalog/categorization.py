from dataclasses import dataclass

from stroyhub.catalog.taxonomy import DEFAULT_NORMALIZED_CATEGORIES, get_normalized_category
from stroyhub.parsers.common import normalize_title


@dataclass(frozen=True, kw_only=True)
class CategoryRule:
    slug: str
    name: str
    parent_slug: str | None
    parent_name: str | None
    keywords: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class ManualCategoryOverride:
    category_slug: str
    category_name: str
    parent_slug: str | None = None
    parent_name: str | None = None


@dataclass(frozen=True, kw_only=True)
class SourceCategoryAlias:
    source: str
    raw_category: str
    category_slug: str


@dataclass(frozen=True, kw_only=True)
class CategoryPrediction:
    category_slug: str
    category_name: str
    parent_slug: str | None
    parent_name: str | None
    confidence: float
    matched_keywords: tuple[str, ...]
    source: str


def _default_category_rules() -> tuple[CategoryRule, ...]:
    rules: list[CategoryRule] = []
    for category in DEFAULT_NORMALIZED_CATEGORIES:
        if not category.keywords:
            continue
        parent = (
            get_normalized_category(category.parent_slug)
            if category.parent_slug is not None
            else None
        )
        rules.append(
            CategoryRule(
                slug=category.slug,
                name=category.name,
                parent_slug=category.parent_slug,
                parent_name=parent.name if parent is not None else None,
                keywords=category.keywords,
            )
        )
    return tuple(rules)


DEFAULT_CATEGORY_RULES: tuple[CategoryRule, ...] = _default_category_rules()
DEFAULT_SOURCE_CATEGORY_ALIASES: tuple[SourceCategoryAlias, ...] = (
    SourceCategoryAlias(
        source="2gis",
        raw_category="Гипсокартон и комплектующие",
        category_slug="drywall",
    ),
    SourceCategoryAlias(
        source="2gis",
        raw_category="Древесно-плитные материалы",
        category_slug="osb_plywood_dsp",
    ),
    SourceCategoryAlias(
        source="2gis",
        raw_category="Фанера, ОСП",
        category_slug="osb_plywood_dsp",
    ),
    SourceCategoryAlias(
        source="2gis",
        raw_category="Профлист, металлочерепица",
        category_slug="profiled_sheet",
    ),
    SourceCategoryAlias(
        source="2gis",
        raw_category="Сайдинг, фасадные панели",
        category_slug="siding_facade_panels",
    ),
    SourceCategoryAlias(
        source="2gis",
        raw_category="Технониколь Водосточная система ПВХ",
        category_slug="drainage_systems",
    ),
    SourceCategoryAlias(
        source="2gis",
        raw_category="Гидропароизоляция",
        category_slug="vapor_barrier_membranes",
    ),
    SourceCategoryAlias(
        source="2gis",
        raw_category="Геотекстиль",
        category_slug="geotextiles_fabrics",
    ),
    SourceCategoryAlias(
        source="2gis",
        raw_category="Пенополистирол",
        category_slug="foam_insulation",
    ),
    SourceCategoryAlias(
        source="2gis",
        raw_category="Экструдированный пенополистирол",
        category_slug="foam_insulation",
    ),
    SourceCategoryAlias(source="2gis", raw_category="Пена монтажная", category_slug="foams"),
    SourceCategoryAlias(source="2gis", raw_category="Герметик", category_slug="sealants"),
    SourceCategoryAlias(source="2gis", raw_category="Дюбель", category_slug="dowels"),
    SourceCategoryAlias(source="2gis", raw_category="Саморезы стеновые", category_slug="screws"),
    SourceCategoryAlias(
        source="2gis",
        raw_category="Саморезы кровельные",
        category_slug="roofing_accessories",
    ),
    SourceCategoryAlias(source="2gis", raw_category="Окна VEKA ПВХ", category_slug="windows"),
    SourceCategoryAlias(
        source="2gis",
        raw_category="Двери печные, каминные",
        category_slug="doors",
    ),
    SourceCategoryAlias(source="2gis", raw_category="Краски düfa", category_slug="paints_enamels"),
    SourceCategoryAlias(source="unicom", raw_category="Цемент", category_slug="cement"),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Сухие клеевые смеси",
        category_slug="tile_adhesives",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Блоки строительные",
        category_slug="bricks_blocks",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Древесно-плитные материалы",
        category_slug="osb_plywood_dsp",
    ),
    SourceCategoryAlias(source="unicom", raw_category="Профнастил", category_slug="profiled_sheet"),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Краски для наружных работ",
        category_slug="paints_enamels",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Трубы металлические",
        category_slug="metal_pipes",
    ),
    SourceCategoryAlias(source="metalltorg", raw_category="Кирпич", category_slug="bricks_blocks"),
    SourceCategoryAlias(
        source="metalltorg",
        raw_category="Гипсокартон и комплектующие",
        category_slug="drywall",
    ),
)


def _source_category_alias_index(
    aliases: tuple[SourceCategoryAlias, ...],
) -> dict[tuple[str, str], SourceCategoryAlias]:
    return {
        (_normalize_source(alias.source), normalize_title(alias.raw_category)): alias
        for alias in aliases
    }


class RuleBasedCategorizer:
    def __init__(
        self,
        rules: tuple[CategoryRule, ...] = DEFAULT_CATEGORY_RULES,
        source_category_aliases: tuple[SourceCategoryAlias, ...] = DEFAULT_SOURCE_CATEGORY_ALIASES,
    ) -> None:
        self._rules = rules
        self._source_category_aliases = _source_category_alias_index(source_category_aliases)

    def categorize(
        self,
        *,
        title: str,
        source: str | None = None,
        category_raw: str | None = None,
        description: str | None = None,
        manual_override: ManualCategoryOverride | None = None,
    ) -> CategoryPrediction | None:
        if manual_override is not None:
            return CategoryPrediction(
                category_slug=manual_override.category_slug,
                category_name=manual_override.category_name,
                parent_slug=manual_override.parent_slug,
                parent_name=manual_override.parent_name,
                confidence=1.0,
                matched_keywords=(),
                source="manual_override",
            )

        alias_prediction = self._source_category_alias_prediction(
            source=source,
            category_raw=category_raw,
        )
        if alias_prediction is not None:
            return alias_prediction

        title_text = normalize_title(title)
        category_text = normalize_title(category_raw or "")
        description_text = normalize_title(description or "")

        best_prediction: CategoryPrediction | None = None
        best_score = 0
        for rule in self._rules:
            score, matched_keywords = self._score_rule(
                rule,
                title_text=title_text,
                category_text=category_text,
                description_text=description_text,
            )
            if score == 0 or score <= best_score:
                continue

            best_score = score
            best_prediction = CategoryPrediction(
                category_slug=rule.slug,
                category_name=rule.name,
                parent_slug=rule.parent_slug,
                parent_name=rule.parent_name,
                confidence=_confidence(score),
                matched_keywords=matched_keywords,
                source="rules",
            )

        return best_prediction

    def _score_rule(
        self,
        rule: CategoryRule,
        *,
        title_text: str,
        category_text: str,
        description_text: str,
    ) -> tuple[int, tuple[str, ...]]:
        score = 0
        matched_keywords: list[str] = []

        for keyword in rule.keywords:
            normalized_keyword = normalize_title(keyword)
            matched = False
            if normalized_keyword in title_text:
                score += 3
                if " " in normalized_keyword or normalized_keyword == title_text:
                    score += 6
                matched = True
            if category_text and normalized_keyword in category_text:
                score += 4
                if " " in normalized_keyword or normalized_keyword == category_text:
                    score += 4
                matched = True
            if description_text and normalized_keyword in description_text:
                score += 1
                matched = True
            if matched:
                matched_keywords.append(keyword)

        return score, tuple(matched_keywords)

    def _source_category_alias_prediction(
        self,
        *,
        source: str | None,
        category_raw: str | None,
    ) -> CategoryPrediction | None:
        if source is None or category_raw is None:
            return None

        alias = self._source_category_aliases.get(
            (_normalize_source(source), normalize_title(category_raw))
        )
        if alias is None:
            return None

        category = get_normalized_category(alias.category_slug)
        if category is None:
            return None

        parent = (
            get_normalized_category(category.parent_slug)
            if category.parent_slug is not None
            else None
        )
        return CategoryPrediction(
            category_slug=category.slug,
            category_name=category.name,
            parent_slug=category.parent_slug,
            parent_name=parent.name if parent is not None else None,
            confidence=0.98,
            matched_keywords=(alias.raw_category,),
            source="source_category_alias",
        )


def _confidence(score: int) -> float:
    return min(0.95, 0.45 + (score * 0.08))


def _normalize_source(source: str) -> str:
    return source.strip().lower()
