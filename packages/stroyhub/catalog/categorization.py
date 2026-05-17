from dataclasses import dataclass

from stroyhub.parsers.common import normalize_title


@dataclass(frozen=True, kw_only=True)
class CategoryRule:
    slug: str
    name: str
    keywords: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class ManualCategoryOverride:
    category_slug: str
    category_name: str


@dataclass(frozen=True, kw_only=True)
class CategoryPrediction:
    category_slug: str
    category_name: str
    confidence: float
    matched_keywords: tuple[str, ...]
    source: str


DEFAULT_CATEGORY_RULES: tuple[CategoryRule, ...] = (
    CategoryRule(
        slug="cement",
        name="Цемент",
        keywords=("цемент", "портландцемент", "м500", "м400", "m500", "m400"),
    ),
    CategoryRule(
        slug="dry_mixes",
        name="Сухие смеси",
        keywords=("сухая смесь", "штукатурка", "шпаклевка", "шпатлевка", "клей плиточный"),
    ),
    CategoryRule(
        slug="aggregates",
        name="Песок и щебень",
        keywords=("песок", "щебень", "гравий", "пгс", "отсев"),
    ),
    CategoryRule(
        slug="bricks_blocks",
        name="Кирпич и блоки",
        keywords=("кирпич", "газоблок", "пеноблок", "керамзитоблок", "блок строительный"),
    ),
    CategoryRule(
        slug="lumber",
        name="Пиломатериалы",
        keywords=("доска", "брус", "рейка", "фанера", "osb", "осп", "дсп"),
    ),
    CategoryRule(
        slug="metal",
        name="Металлопрокат",
        keywords=("арматура", "профнастил", "труба профильная", "уголок", "швеллер", "лист"),
    ),
    CategoryRule(
        slug="roofing",
        name="Кровля",
        keywords=("кровля", "ондулин", "металлочерепица", "шифер", "рубероид", "водосток"),
    ),
    CategoryRule(
        slug="insulation",
        name="Утеплители",
        keywords=("утеплитель", "минвата", "пеноплекс", "пенополистирол", "изовер", "вата"),
    ),
    CategoryRule(
        slug="fasteners",
        name="Крепеж",
        keywords=("саморез", "гвозд", "дюбель", "анкера", "анкер", "болт", "гайка"),
    ),
    CategoryRule(
        slug="paint_coatings",
        name="Краски и покрытия",
        keywords=("краска", "эмаль", "грунтовка", "лак", "пропитка", "антисептик"),
    ),
)


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
                matched = True
            if category_text and normalized_keyword in category_text:
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
