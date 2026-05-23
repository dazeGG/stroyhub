from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.catalog.eligibility import is_matchable_source_product
from stroyhub.ml.matching import (
    ProductMatchCandidate,
    SourceProductLike,
    generate_product_match_candidates,
)
from stroyhub.models import Shop, SourceProduct


@dataclass(frozen=True, kw_only=True)
class MatchCandidateFilters:
    source: str | None = None
    shop_id: int | None = None
    category_id: int | None = None
    category_raw: str | None = None
    min_confidence: float = 0.75
    max_confidence: float | None = None
    limit: int = 50
    allow_category_mismatch: bool = False


@dataclass(frozen=True, kw_only=True)
class MatchCandidateProduct:
    id: int
    source: str
    shop_id: int
    shop_name: str
    shop_source_id: str
    title: str
    normalized_title: str
    category_id: int | None
    category_raw: str | None


@dataclass(frozen=True, kw_only=True)
class MatchCandidateReason:
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
class MatchCandidatePair:
    left: MatchCandidateProduct
    right: MatchCandidateProduct
    confidence: float
    reason: MatchCandidateReason


@dataclass(frozen=True, kw_only=True)
class MatchCandidateReport:
    products_considered: int
    candidates: list[MatchCandidatePair]


class MatchCandidateCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_candidates(self, filters: MatchCandidateFilters) -> MatchCandidateReport:
        products = self._list_active_products(filters)
        products_by_id = {product.id: product for product in products}
        candidates = generate_product_match_candidates(
            cast("list[SourceProductLike]", products),
            min_confidence=filters.min_confidence,
            allow_category_mismatch=filters.allow_category_mismatch,
        )
        if filters.max_confidence is not None:
            candidates = tuple(
                candidate
                for candidate in candidates
                if candidate.confidence <= filters.max_confidence
            )
        if filters.limit > 0:
            candidates = candidates[: filters.limit]

        return MatchCandidateReport(
            products_considered=len(products),
            candidates=[
                self._candidate_pair(candidate, products_by_id=products_by_id)
                for candidate in candidates
            ],
        )

    def _list_active_products(self, filters: MatchCandidateFilters) -> list[MatchCandidateProduct]:
        statement = (
            select(SourceProduct, Shop)
            .join(Shop, SourceProduct.shop_id == Shop.id)
            .where(SourceProduct.is_active.is_(True))
            .order_by(SourceProduct.category_id.asc(), SourceProduct.normalized_title.asc())
        )
        if filters.source is not None:
            source = filters.source.strip()
            if source:
                statement = statement.where(SourceProduct.source == source)
        if filters.shop_id is not None:
            statement = statement.where(SourceProduct.shop_id == filters.shop_id)
        if filters.category_id is not None:
            statement = statement.where(SourceProduct.category_id == filters.category_id)
        if filters.category_raw is not None:
            category_raw = filters.category_raw.strip()
            if category_raw:
                statement = statement.where(SourceProduct.category_raw == category_raw)

        return [
            MatchCandidateProduct(
                id=product.id,
                source=product.source,
                shop_id=shop.id,
                shop_name=shop.name,
                shop_source_id=shop.source_id,
                title=product.title,
                normalized_title=product.normalized_title,
                category_id=product.category_id,
                category_raw=product.category_raw,
            )
            for product, shop in self._session.execute(statement)
            if is_matchable_source_product(
                product.raw,
                is_not_product=product.is_not_product,
            )
        ]

    def _candidate_pair(
        self,
        candidate: ProductMatchCandidate,
        *,
        products_by_id: dict[int, MatchCandidateProduct],
    ) -> MatchCandidatePair:
        reason = candidate.reason
        return MatchCandidatePair(
            left=products_by_id[candidate.left.id],
            right=products_by_id[candidate.right.id],
            confidence=candidate.confidence,
            reason=MatchCandidateReason(
                method=reason.method,
                exact_title=reason.exact_title,
                matched_normalized_title=reason.matched_normalized_title,
                token_overlap=reason.token_overlap,
                left_only_tokens=reason.left_only_tokens,
                right_only_tokens=reason.right_only_tokens,
                ignored_tokens=reason.ignored_tokens,
                blocked_by=reason.blocked_by,
                token_similarity=reason.token_similarity,
                same_category=reason.same_category,
            ),
        )
