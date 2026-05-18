from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

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


@dataclass(frozen=True, kw_only=True)
class ProductMatchReason:
    method: str
    exact_title: bool
    matched_normalized_title: str | None
    token_overlap: tuple[str, ...]
    left_only_tokens: tuple[str, ...]
    right_only_tokens: tuple[str, ...]
    ignored_tokens: tuple[str, ...]
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


def _jaccard(left_tokens: set[str], right_tokens: set[str]) -> float:
    if not left_tokens and not right_tokens:
        return 0.0

    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
