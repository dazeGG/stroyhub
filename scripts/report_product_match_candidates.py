#!/usr/bin/env python
import argparse
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session
from stroyhub.catalog.eligibility import is_matchable_source_product
from stroyhub.db import SessionLocal
from stroyhub.ml.matching import ProductMatchCandidate, generate_product_match_candidates
from stroyhub.models import Shop, SourceProduct


@dataclass(frozen=True, kw_only=True)
class MatchReportProduct:
    id: int
    source: str
    shop_id: int
    shop_name: str
    shop_source_id: str
    title: str
    normalized_title: str
    category_id: int | None
    category_raw: str | None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print product match candidates for manual review."
    )
    parser.add_argument("--source")
    parser.add_argument("--shop-id", type=int)
    parser.add_argument("--category-id", type=int)
    parser.add_argument("--category-raw")
    parser.add_argument("--min-confidence", type=float, default=0.75)
    parser.add_argument("--max-confidence", type=float)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--allow-category-mismatch", action="store_true")
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        products = list_active_products(
            session,
            source=args.source,
            shop_id=args.shop_id,
            category_id=args.category_id,
            category_raw=args.category_raw,
        )

    candidates = generate_report_candidates(
        products,
        min_confidence=args.min_confidence,
        max_confidence=args.max_confidence,
        limit=args.limit,
        allow_category_mismatch=args.allow_category_mismatch,
    )
    print_report(products, candidates)
    return 0


def list_active_products(
    session: Session,
    *,
    source: str | None,
    shop_id: int | None,
    category_id: int | None,
    category_raw: str | None,
) -> list[MatchReportProduct]:
    statement = (
        select(SourceProduct, Shop)
        .join(Shop, SourceProduct.shop_id == Shop.id)
        .where(SourceProduct.is_active.is_(True))
        .order_by(SourceProduct.category_id.asc(), SourceProduct.normalized_title.asc())
    )
    if source is not None:
        statement = statement.where(SourceProduct.source == source)
    if shop_id is not None:
        statement = statement.where(SourceProduct.shop_id == shop_id)
    if category_id is not None:
        statement = statement.where(SourceProduct.category_id == category_id)
    if category_raw is not None:
        statement = statement.where(SourceProduct.category_raw == category_raw)

    return [
        MatchReportProduct(
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
        for product, shop in session.execute(statement)
        if is_matchable_source_product(
            product.raw,
            is_not_product=product.is_not_product,
        )
    ]


def generate_report_candidates(
    products: Sequence[MatchReportProduct],
    *,
    min_confidence: float,
    max_confidence: float | None,
    limit: int,
    allow_category_mismatch: bool,
) -> tuple[ProductMatchCandidate, ...]:
    candidates = generate_product_match_candidates(
        products,
        min_confidence=min_confidence,
        allow_category_mismatch=allow_category_mismatch,
    )
    if max_confidence is not None:
        candidates = tuple(
            candidate for candidate in candidates if candidate.confidence <= max_confidence
        )
    if limit > 0:
        candidates = candidates[:limit]

    return candidates


def print_report(
    products: Sequence[MatchReportProduct],
    candidates: Sequence[ProductMatchCandidate],
) -> None:
    products_by_id = {product.id: product for product in products}
    print(
        "product match candidate summary: "
        f"products={len(products)} "
        f"candidates={len(candidates)}"
    )
    for candidate in candidates:
        left = products_by_id[candidate.left.id]
        right = products_by_id[candidate.right.id]
        print(format_candidate(candidate, left=left, right=right))
        print(format_reason(candidate))


def format_candidate(
    candidate: ProductMatchCandidate,
    *,
    left: MatchReportProduct,
    right: MatchReportProduct,
) -> str:
    return (
        "match candidate: "
        f"confidence={candidate.confidence:.3f} "
        f"method={candidate.reason.method} "
        f"left_id={left.id} "
        f"left_shop={left.shop_name} "
        f"left_title={left.title} "
        f"right_id={right.id} "
        f"right_shop={right.shop_name} "
        f"right_title={right.title} "
        f"category_id={_format_optional_int(left.category_id)} "
        f"category_raw={left.category_raw or '-'}"
    )


def format_reason(candidate: ProductMatchCandidate) -> str:
    reason = candidate.reason
    return (
        "  reason: "
        f"matched_normalized_title={reason.matched_normalized_title or '-'} "
        f"token_similarity={reason.token_similarity:.3f} "
        f"same_category={reason.same_category} "
        f"overlap={_format_tokens(reason.token_overlap)} "
        f"left_only={_format_tokens(reason.left_only_tokens)} "
        f"right_only={_format_tokens(reason.right_only_tokens)} "
        f"ignored={_format_tokens(reason.ignored_tokens)}"
    )


def _format_optional_int(value: int | None) -> str:
    if value is None:
        return "-"
    return str(value)


def _format_tokens(tokens: tuple[str, ...]) -> str:
    if not tokens:
        return "-"
    return ",".join(tokens)


if __name__ == "__main__":
    raise SystemExit(main())
