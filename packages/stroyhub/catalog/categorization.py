from dataclasses import dataclass
from typing import Literal

from stroyhub.catalog.taxonomy import DEFAULT_NORMALIZED_CATEGORIES, get_normalized_category
from stroyhub.catalog.tokenization import tokenize_normalized_text
from stroyhub.parsers.common import normalize_title

CategoryDecisionStatus = Literal["assigned", "needs_review", "unmapped", "non_product"]
_LOW_CONFIDENCE_REVIEW_THRESHOLD = 0.65


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
    category_name: str | None = None
    parent_slug: str | None = None
    parent_name: str | None = None


@dataclass(frozen=True, kw_only=True)
class NonProductSourceCategory:
    source: str
    raw_category: str


@dataclass(frozen=True, kw_only=True)
class CategoryPrediction:
    category_slug: str
    category_name: str
    parent_slug: str | None
    parent_name: str | None
    confidence: float
    matched_keywords: tuple[str, ...]
    source: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class CategorySuggestion:
    category_slug: str
    category_name: str
    parent_slug: str | None
    parent_name: str | None
    confidence: float
    matched_keywords: tuple[str, ...]
    source: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class CategoryDecision:
    status: CategoryDecisionStatus
    confidence: float
    prediction: CategoryPrediction | None
    suggestions: tuple[CategorySuggestion, ...]
    reasons: tuple[str, ...]


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
        raw_category="СИП ПАНЕЛИ",
        category_slug="sip_panels",
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
    SourceCategoryAlias(
        source="2gis",
        raw_category="Утеплитель межвенцовый",
        category_slug="natural_fiber_insulation",
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
    SourceCategoryAlias(
        source="unicom",
        raw_category="Проходные переключатели",
        category_slug="wiring_devices",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Материалы для изоляции, крепления и маркировки",
        category_slug="cable_routing",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Дифференциальные автоматы",
        category_slug="electrical_panels",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Прочий столярно-слесарный инструмент",
        category_slug="hand_tools",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Муфты полипропиленовые",
        category_slug="water_pipes_fittings",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Аксессуары для розеток и выключателей",
        category_slug="wiring_devices",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Наконечники и гильзы силовые",
        category_slug="cables_wires",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Ленты",
        category_slug="abrasives_tapes_consumables",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Комплектующие для вентиляционных систем",
        category_slug="ventilation",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Силовые шины",
        category_slug="electrical_panels",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Клеммы монтажные соединительные",
        category_slug="cables_wires",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Аксессуары для лотков",
        category_slug="cable_routing",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Шарнирно-губцевый инструмент",
        category_slug="hand_tools",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Лента светодиодная",
        category_slug="lighting",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Контакторы",
        category_slug="electrical_panels",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Насадки",
        category_slug="power_tool_accessories",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Аксессуары для сантехники",
        category_slug="sanitary_ware",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Прочие фитинги",
        category_slug="water_pipes_fittings",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Комплектующие для светодиодных лент",
        category_slug="lighting",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Наконечники и гильзы",
        category_slug="cables_wires",
    ),
    SourceCategoryAlias(
        source="unicom",
        raw_category="Аксессуары и комплектующие для металлорукавов",
        category_slug="cable_routing",
    ),
    SourceCategoryAlias(source="metalltorg", raw_category="Кирпич", category_slug="bricks_blocks"),
    SourceCategoryAlias(
        source="metalltorg",
        raw_category="Гипсокартон и комплектующие",
        category_slug="drywall",
    ),
)
DEFAULT_NON_PRODUCT_SOURCE_CATEGORIES: tuple[NonProductSourceCategory, ...] = (
    NonProductSourceCategory(source="2gis", raw_category="Работа"),
)


def _source_category_alias_index(
    aliases: tuple[SourceCategoryAlias, ...],
) -> dict[tuple[str, str], SourceCategoryAlias]:
    return {
        (_normalize_source(alias.source), normalize_title(alias.raw_category)): alias
        for alias in aliases
    }


def _source_category_set(
    categories: tuple[NonProductSourceCategory, ...],
) -> set[tuple[str, str]]:
    return {
        (_normalize_source(category.source), normalize_title(category.raw_category))
        for category in categories
    }


class RuleBasedCategorizer:
    def __init__(
        self,
        rules: tuple[CategoryRule, ...] = DEFAULT_CATEGORY_RULES,
        source_category_aliases: tuple[SourceCategoryAlias, ...] = DEFAULT_SOURCE_CATEGORY_ALIASES,
        non_product_source_categories: tuple[
            NonProductSourceCategory, ...
        ] = DEFAULT_NON_PRODUCT_SOURCE_CATEGORIES,
    ) -> None:
        self._rules = rules
        self._source_category_aliases = _source_category_alias_index(source_category_aliases)
        self._non_product_source_categories = _source_category_set(non_product_source_categories)

    def categorize(
        self,
        *,
        title: str,
        source: str | None = None,
        category_raw: str | None = None,
        description: str | None = None,
        manual_override: ManualCategoryOverride | None = None,
    ) -> CategoryPrediction | None:
        decision = self.decide(
            title=title,
            source=source,
            category_raw=category_raw,
            description=description,
            manual_override=manual_override,
        )
        return decision.prediction if decision.status == "assigned" else None

    def decide(
        self,
        *,
        title: str,
        source: str | None = None,
        category_raw: str | None = None,
        description: str | None = None,
        manual_override: ManualCategoryOverride | None = None,
    ) -> CategoryDecision:
        if manual_override is not None:
            prediction = CategoryPrediction(
                category_slug=manual_override.category_slug,
                category_name=manual_override.category_name,
                parent_slug=manual_override.parent_slug,
                parent_name=manual_override.parent_name,
                confidence=1.0,
                matched_keywords=(),
                source="manual_override",
                reasons=("manual_category_override",),
            )
            return _assigned(prediction, reasons=("manual_category_override",))

        if self._is_non_product_source_category(source=source, category_raw=category_raw):
            return CategoryDecision(
                status="non_product",
                confidence=1.0,
                prediction=None,
                suggestions=(),
                reasons=("non_product_source_category",),
            )

        alias_prediction = self._source_category_alias_prediction(
            source=source,
            category_raw=category_raw,
        )
        if alias_prediction is not None:
            return _assigned(alias_prediction, reasons=alias_prediction.reasons)

        title_text = normalize_title(title)
        category_text = normalize_title(category_raw or "")
        description_text = normalize_title(description or "")
        title_tokens = tokenize_normalized_text(title_text)
        category_tokens = tokenize_normalized_text(category_text)
        description_tokens = tokenize_normalized_text(description_text)

        scored_predictions: list[tuple[int, CategoryPrediction]] = []
        for rule in self._rules:
            score, matched_keywords = self._score_rule(
                rule,
                title_text=title_text,
                title_tokens=title_tokens,
                category_text=category_text,
                category_tokens=category_tokens,
                description_text=description_text,
                description_tokens=description_tokens,
            )
            if score == 0:
                continue

            scored_predictions.append(
                (
                    score,
                    CategoryPrediction(
                        category_slug=rule.slug,
                        category_name=rule.name,
                        parent_slug=rule.parent_slug,
                        parent_name=rule.parent_name,
                        confidence=_confidence(score),
                        matched_keywords=matched_keywords,
                        source="rules",
                        reasons=(f"rule_score:{score}",),
                    ),
                )
            )

        if not scored_predictions:
            return CategoryDecision(
                status="unmapped",
                confidence=0.0,
                prediction=None,
                suggestions=(),
                reasons=("no_category_rule_matched",),
            )

        scored_predictions.sort(
            key=lambda item: (-item[0], item[1].category_slug, item[1].category_name)
        )
        best_score = scored_predictions[0][0]
        best_predictions = tuple(
            prediction for score, prediction in scored_predictions if score == best_score
        )
        if len({prediction.category_slug for prediction in best_predictions}) > 1:
            suggestions = tuple(_suggestion(prediction) for prediction in best_predictions)
            return CategoryDecision(
                status="needs_review",
                confidence=best_predictions[0].confidence,
                prediction=None,
                suggestions=suggestions,
                reasons=("conflicting_category_rule_scores", f"rule_score:{best_score}"),
            )

        prediction = best_predictions[0]
        if prediction.confidence < _LOW_CONFIDENCE_REVIEW_THRESHOLD:
            return CategoryDecision(
                status="needs_review",
                confidence=prediction.confidence,
                prediction=None,
                suggestions=(_suggestion(prediction),),
                reasons=("low_confidence_category_rule", *prediction.reasons),
            )

        return _assigned(prediction, reasons=prediction.reasons)

    def _is_non_product_source_category(
        self,
        *,
        source: str | None,
        category_raw: str | None,
    ) -> bool:
        if source is None or category_raw is None:
            return False

        return (_normalize_source(source), normalize_title(category_raw)) in (
            self._non_product_source_categories
        )

    def _score_rule(
        self,
        rule: CategoryRule,
        *,
        title_text: str,
        title_tokens: tuple[str, ...],
        category_text: str,
        category_tokens: tuple[str, ...],
        description_text: str,
        description_tokens: tuple[str, ...],
    ) -> tuple[int, tuple[str, ...]]:
        score = 0
        matched_keywords: list[str] = []

        for keyword in rule.keywords:
            normalized_keyword = normalize_title(keyword)
            keyword_tokens = tokenize_normalized_text(normalized_keyword)
            matched = False
            title_match, title_phrase = _keyword_matches_text(
                normalized_keyword,
                keyword_tokens,
                title_text,
                title_tokens,
            )
            if title_match:
                score += 3
                if title_phrase or normalized_keyword == title_text:
                    score += 6
                matched = True
            category_match, category_phrase = _keyword_matches_text(
                normalized_keyword,
                keyword_tokens,
                category_text,
                category_tokens,
            )
            if category_match:
                score += 4
                if category_phrase or normalized_keyword == category_text:
                    score += 4
                matched = True
            description_match, _ = _keyword_matches_text(
                normalized_keyword,
                keyword_tokens,
                description_text,
                description_tokens,
            )
            if description_match:
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
        if category is None and alias.category_name is None:
            return None

        parent = (
            get_normalized_category(category.parent_slug)
            if category is not None and category.parent_slug is not None
            else None
        )
        return CategoryPrediction(
            category_slug=category.slug if category is not None else alias.category_slug,
            category_name=category.name if category is not None else alias.category_name or "",
            parent_slug=category.parent_slug if category is not None else alias.parent_slug,
            parent_name=(
                parent.name
                if parent is not None
                else alias.parent_name if category is None else None
            ),
            confidence=0.98,
            matched_keywords=(alias.raw_category,),
            source="source_category_alias",
            reasons=("source_category_alias",),
        )


def _assigned(
    prediction: CategoryPrediction,
    *,
    reasons: tuple[str, ...],
) -> CategoryDecision:
    return CategoryDecision(
        status="assigned",
        confidence=prediction.confidence,
        prediction=prediction,
        suggestions=(_suggestion(prediction),),
        reasons=reasons,
    )


def _suggestion(prediction: CategoryPrediction) -> CategorySuggestion:
    return CategorySuggestion(
        category_slug=prediction.category_slug,
        category_name=prediction.category_name,
        parent_slug=prediction.parent_slug,
        parent_name=prediction.parent_name,
        confidence=prediction.confidence,
        matched_keywords=prediction.matched_keywords,
        source=prediction.source,
        reasons=prediction.reasons,
    )


def _confidence(score: int) -> float:
    return min(0.95, 0.45 + (score * 0.08))


def _normalize_source(source: str) -> str:
    return source.strip().lower()


def _keyword_matches_text(
    normalized_keyword: str,
    keyword_tokens: tuple[str, ...],
    text: str,
    text_tokens: tuple[str, ...],
) -> tuple[bool, bool]:
    if not normalized_keyword or not keyword_tokens or not text:
        return False, False

    if len(keyword_tokens) == 1:
        return keyword_tokens[0] in text_tokens, False

    if normalized_keyword in text:
        return True, True

    return _contains_token_sequence(text_tokens, keyword_tokens), True


def _contains_token_sequence(
    text_tokens: tuple[str, ...],
    keyword_tokens: tuple[str, ...],
) -> bool:
    if len(keyword_tokens) > len(text_tokens):
        return False

    last_start = len(text_tokens) - len(keyword_tokens)
    for start in range(last_start + 1):
        if text_tokens[start : start + len(keyword_tokens)] == keyword_tokens:
            return True
    return False
