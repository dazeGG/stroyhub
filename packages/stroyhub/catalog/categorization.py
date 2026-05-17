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


class RuleBasedCategorizer:
    def __init__(self, rules: tuple[CategoryRule, ...] = DEFAULT_CATEGORY_RULES) -> None:
        self._rules = rules

    def categorize(
        self,
        *,
        title: str,
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


def _confidence(score: int) -> float:
    return min(0.95, 0.45 + (score * 0.08))
