import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from stroyhub.catalog.attributes import ExtractedAttribute, extract_title_attributes
from stroyhub.catalog.tokenization import tokenize_normalized_text
from stroyhub.parsers.common import normalize_title

_LOW_VALUE_TOKENS = frozenset(
    {
        "в",
        "для",
        "до",
        "и",
        "из",
        "на",
        "от",
        "по",
        "под",
        "с",
        "со",
        "материал",
        "материалы",
        "строительный",
        "универсальная",
        "универсальное",
        "универсальный",
    }
)
_TOKEN_ALIASES = {
    "плитки": "плиточный",
    "плиточная": "плиточный",
    "плиточное": "плиточный",
}
_ATTRIBUTE_BLOCKER_KINDS = frozenset({"dimension", "package_count", "volume", "weight"})
_GRADE_PATTERN = re.compile(r"^[мm]\d{2,3}$", re.IGNORECASE)
_COLOR_ALIASES = {
    "бежевый": "бежевый",
    "бежевая": "бежевый",
    "бежевое": "бежевый",
    "белый": "белый",
    "белая": "белый",
    "белое": "белый",
    "графит": "графит",
    "зеленый": "зеленый",
    "зеленая": "зеленый",
    "зеленое": "зеленый",
    "коричневый": "коричневый",
    "коричневая": "коричневый",
    "коричневое": "коричневый",
    "красный": "красный",
    "красная": "красный",
    "красное": "красный",
    "серый": "серый",
    "серая": "серый",
    "серое": "серый",
    "черный": "черный",
    "черная": "черный",
    "черное": "черный",
}
_FINISH_MATERIAL_TOKENS = frozenset(
    {
        "панель",
        "панели",
        "сайдинг",
        "фасадная",
        "фасадный",
        "краска",
        "эмаль",
    }
)
_FINISH_MATERIAL_CATEGORY_WORDS = frozenset(
    {
        "лакокрасочные",
        "лкм",
        "отделочные",
        "сайдинг",
        "фасад",
    }
)


class SourceProductLike(Protocol):
    id: int
    source: str
    shop_id: int
    title: str
    normalized_title: str
    category_id: int | None
    category_raw: str | None


@dataclass(frozen=True, kw_only=True)
class MatchProduct:
    id: int
    source: str
    shop_id: int
    title: str
    normalized_title: str
    category_id: int | None
    category_raw: str | None
    tokens: tuple[str, ...]
    ignored_tokens: tuple[str, ...]
    attributes: tuple[ExtractedAttribute, ...]
    grades: tuple[str, ...]
    colors: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class ProductMatchReason:
    method: str
    exact_title: bool
    matched_normalized_title: str | None
    token_overlap: tuple[str, ...]
    left_only_tokens: tuple[str, ...]
    right_only_tokens: tuple[str, ...]
    ignored_tokens: tuple[str, ...]
    blocked_by: tuple[str, ...]
    token_similarity: float
    same_category: bool | None


@dataclass(frozen=True, kw_only=True)
class ProductMatchCandidate:
    left: MatchProduct
    right: MatchProduct
    confidence: float
    reason: ProductMatchReason


def generate_product_match_candidates(
    products: Iterable[SourceProductLike],
    *,
    min_confidence: float = 0.75,
    allow_category_mismatch: bool = False,
) -> tuple[ProductMatchCandidate, ...]:
    """Generate conservative in-memory match candidates without persistence."""
    prepared_products = tuple(_prepare_product(product) for product in products)
    candidates: list[ProductMatchCandidate] = []

    for left_index, left in enumerate(prepared_products):
        for right in prepared_products[left_index + 1 :]:
            candidate = _candidate_for_pair(
                left,
                right,
                allow_category_mismatch=allow_category_mismatch,
            )
            if candidate is not None and candidate.confidence >= min_confidence:
                candidates.append(candidate)

    return tuple(sorted(candidates, key=lambda candidate: candidate.confidence, reverse=True))


def _prepare_product(product: SourceProductLike) -> MatchProduct:
    normalized_title = product.normalized_title or normalize_title(product.title)
    tokens, ignored_tokens = _matching_tokens(normalized_title)
    attributes = extract_title_attributes(product.title)
    return MatchProduct(
        id=product.id,
        source=product.source,
        shop_id=product.shop_id,
        title=product.title,
        normalized_title=normalized_title,
        category_id=product.category_id,
        category_raw=product.category_raw,
        tokens=tokens,
        ignored_tokens=ignored_tokens,
        attributes=attributes,
        grades=_grade_tokens(tokens),
        colors=_color_tokens(tokens),
    )


def _candidate_for_pair(
    left: MatchProduct,
    right: MatchProduct,
    *,
    allow_category_mismatch: bool,
) -> ProductMatchCandidate | None:
    same_category = _same_category(left, right)
    if same_category is False and not allow_category_mismatch:
        return None

    blocked_by = _blocking_reasons(left, right)
    if blocked_by:
        return None

    exact_title = left.normalized_title == right.normalized_title
    left_tokens = set(left.tokens)
    right_tokens = set(right.tokens)
    ignored_tokens = tuple(sorted(set(left.ignored_tokens) | set(right.ignored_tokens)))
    token_overlap = tuple(sorted(left_tokens & right_tokens))
    left_only_tokens = tuple(sorted(left_tokens - right_tokens))
    right_only_tokens = tuple(sorted(right_tokens - left_tokens))
    token_similarity = _jaccard(left_tokens, right_tokens)

    if exact_title:
        confidence = 1.0
        method = "exact_normalized_title"
    else:
        confidence = token_similarity
        method = "token_similarity"

    if same_category is None:
        confidence *= 0.95
    elif same_category is False:
        confidence *= 0.9

    reason = ProductMatchReason(
        method=method,
        exact_title=exact_title,
        matched_normalized_title=left.normalized_title if exact_title else None,
        token_overlap=token_overlap,
        left_only_tokens=left_only_tokens,
        right_only_tokens=right_only_tokens,
        ignored_tokens=ignored_tokens,
        blocked_by=blocked_by,
        token_similarity=round(token_similarity, 3),
        same_category=same_category,
    )
    return ProductMatchCandidate(
        left=left,
        right=right,
        confidence=round(confidence, 3),
        reason=reason,
    )


def _same_category(left: MatchProduct, right: MatchProduct) -> bool | None:
    if left.category_id is not None and right.category_id is not None:
        return left.category_id == right.category_id

    if left.category_raw and right.category_raw:
        return normalize_title(left.category_raw) == normalize_title(right.category_raw)

    return None


def _matching_tokens(normalized_title: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    tokens: list[str] = []
    ignored_tokens: list[str] = []

    for token in tokenize_normalized_text(normalized_title):
        normalized_token = _TOKEN_ALIASES.get(token, token)
        if normalized_token in _LOW_VALUE_TOKENS:
            ignored_tokens.append(token)
            continue
        tokens.append(normalized_token)

    return tuple(tokens), tuple(ignored_tokens)


def _grade_tokens(tokens: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(token for token in tokens if _GRADE_PATTERN.match(token))


def _color_tokens(tokens: tuple[str, ...]) -> tuple[str, ...]:
    colors = {_COLOR_ALIASES[token] for token in tokens if token in _COLOR_ALIASES}
    return tuple(sorted(colors))


def _blocking_reasons(left: MatchProduct, right: MatchProduct) -> tuple[str, ...]:
    blockers: list[str] = []

    attribute_blockers = _attribute_blockers(left.attributes, right.attributes)
    blockers.extend(attribute_blockers)

    if left.grades and right.grades and set(left.grades).isdisjoint(right.grades):
        blockers.append("grade")

    if (
        left.colors
        and right.colors
        and set(left.colors).isdisjoint(right.colors)
        and _is_finish_material_pair(left, right)
    ):
        blockers.append("color")

    return tuple(blockers)


def _attribute_blockers(
    left_attributes: tuple[ExtractedAttribute, ...],
    right_attributes: tuple[ExtractedAttribute, ...],
) -> tuple[str, ...]:
    left = _attribute_signatures_by_kind(left_attributes)
    right = _attribute_signatures_by_kind(right_attributes)
    blockers: list[str] = []

    for kind in sorted(_ATTRIBUTE_BLOCKER_KINDS):
        left_values = left.get(kind)
        right_values = right.get(kind)
        if left_values and right_values and left_values.isdisjoint(right_values):
            blockers.append(kind)

    return tuple(blockers)


def _attribute_signatures_by_kind(
    attributes: tuple[ExtractedAttribute, ...],
) -> dict[str, set[tuple[str, tuple[Decimal, ...]]]]:
    signatures: dict[str, set[tuple[str, tuple[Decimal, ...]]]] = {}

    for attribute in attributes:
        if attribute.kind not in _ATTRIBUTE_BLOCKER_KINDS:
            continue
        signatures.setdefault(attribute.kind, set()).add((attribute.unit, attribute.values))

    return signatures


def _is_finish_material_pair(left: MatchProduct, right: MatchProduct) -> bool:
    return _is_finish_material(left) and _is_finish_material(right)


def _is_finish_material(product: MatchProduct) -> bool:
    if set(product.tokens) & _FINISH_MATERIAL_TOKENS:
        return True

    if product.category_raw:
        category_words = set(tokenize_normalized_text(normalize_title(product.category_raw)))
        return bool(category_words & _FINISH_MATERIAL_CATEGORY_WORDS)

    return False


def _jaccard(left_tokens: set[str], right_tokens: set[str]) -> float:
    if not left_tokens and not right_tokens:
        return 0.0

    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
