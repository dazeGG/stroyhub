from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import Numeric, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from stroyhub.catalog.operator_decision_history import record_operator_decision
from stroyhub.catalog.products import format_price_text
from stroyhub.catalog.query_helpers import latest_price_subquery
from stroyhub.models import Category, OperatorDecision, Shop, SourceProduct
from stroyhub.parsers.common import JsonObject

PatronReviewAction = Literal["product", "not_product", "skip"]
PatronReviewMode = Literal["needs_review", "patron_rejected"]

_REVIEW_ACTIONS = frozenset(
    {
        "patron_review_product",
        "patron_review_not_product",
        "patron_review_skip",
    }
)


@dataclass(frozen=True, kw_only=True)
class PatronReviewShop:
    id: int
    source: str
    source_id: str
    name: str


@dataclass(frozen=True, kw_only=True)
class PatronReviewCategory:
    id: int
    slug: str
    name: str


@dataclass(frozen=True, kw_only=True)
class PatronReviewLatestPrice:
    price: Decimal | None
    price_kind: str
    price_text: str | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


@dataclass(frozen=True, kw_only=True)
class PatronReviewItem:
    id: int
    source: str
    source_product_id: str | None
    title: str
    normalized_title: str
    description: str | None
    category_id: int | None
    category: PatronReviewCategory | None
    category_raw: str | None
    unit_raw: str | None
    image_url: str | None
    source_updated_at: datetime | None
    last_seen_at: datetime
    is_not_product: bool
    shop: PatronReviewShop
    latest_price: PatronReviewLatestPrice | None
    catalog_eligibility: JsonObject | None
    raw: JsonObject | None


@dataclass(frozen=True, kw_only=True)
class PatronReviewStats:
    total: int
    remaining: int
    reviewed: int
    skipped: int


@dataclass(frozen=True, kw_only=True)
class PatronReviewPage:
    item: PatronReviewItem | None
    stats: PatronReviewStats


@dataclass(frozen=True, kw_only=True)
class PatronReviewDecisionResult:
    action: str
    product_id: int | None
    stats: PatronReviewStats


class PatronReviewQueue:
    def __init__(
        self,
        session: Session,
        *,
        mode: PatronReviewMode = "needs_review",
        min_probability: Decimal = Decimal("0.700"),
    ) -> None:
        self._session = session
        self._mode = mode
        self._min_probability = min_probability

    def current(self) -> PatronReviewPage:
        return PatronReviewPage(
            item=self._next_item(),
            stats=self.stats(),
        )

    def stats(self) -> PatronReviewStats:
        remaining = self._count(self._remaining_predicate())
        reviewed = self._count(
            and_(
                _review_status().in_(("product", "not_product")),
                self._review_mode_predicate(),
            )
        )
        skipped = self._count(
            and_(
                _review_status().in_(("skip", "skipped")),
                self._review_mode_predicate(),
            )
        )
        return PatronReviewStats(
            total=remaining + reviewed + skipped,
            remaining=remaining,
            reviewed=reviewed,
            skipped=skipped,
        )

    def decide(
        self,
        *,
        product_id: int,
        action: PatronReviewAction,
        actor: str | None = "admin",
        reason: str | None = None,
    ) -> PatronReviewDecisionResult:
        product = self._session.get(SourceProduct, product_id)
        if product is None:
            raise ValueError("source product not found")
        if not self._is_remaining_product(product_id):
            raise ValueError("source product is not in Patron review queue")

        previous_state = _product_state(product)
        review_mode = _mode_for_product(product) or self._mode
        now = datetime.now(UTC)
        product.raw = _raw_with_patron_review(
            product.raw,
            action=action,
            actor=actor,
            reason=reason,
            queue=review_mode,
            reviewed_at=now,
        )
        if action in {"product", "not_product"}:
            product.is_not_product = action == "not_product"

        record_operator_decision(
            self._session,
            decision_type="data_quality",
            action=f"patron_review_{action}",
            entity_type="source_product",
            entity_id=product.id,
            source_product_id=product.id,
            category_id=product.category_id,
            actor=actor,
            reason=reason,
            previous_state=previous_state,
            new_state=_product_state(product),
            evidence={
                "source": "patron_review",
                "action": action,
                "queue": review_mode,
                "catalog_eligibility": previous_state.get("catalog_eligibility"),
            },
            decided_at=now,
        )
        self._session.flush()
        return PatronReviewDecisionResult(
            action=action,
            product_id=product.id,
            stats=self.stats(),
        )

    def undo(
        self,
        *,
        actor: str | None = "admin",
        reason: str | None = None,
    ) -> PatronReviewDecisionResult:
        decision = self._last_review_decision(actor=actor)
        if decision is None or decision.source_product_id is None:
            raise ValueError("patron review history is empty")
        previous_state = decision.previous_state
        if not isinstance(previous_state, dict):
            raise ValueError("patron review decision cannot be undone")

        product = self._session.get(SourceProduct, decision.source_product_id)
        if product is None:
            raise ValueError("source product not found")

        current_state = _product_state(product)
        raw = previous_state.get("raw")
        product.raw = raw if isinstance(raw, dict) else None
        is_not_product = previous_state.get("is_not_product")
        if isinstance(is_not_product, bool):
            product.is_not_product = is_not_product

        record_operator_decision(
            self._session,
            decision_type="data_quality",
            action="patron_review_undo",
            entity_type="source_product",
            entity_id=product.id,
            source_product_id=product.id,
            category_id=product.category_id,
            actor=actor,
            reason=reason,
            previous_state=current_state,
            new_state=_product_state(product),
            evidence={
                "source": "patron_review",
                "undone_decision_id": decision.id,
                "undone_action": decision.action,
            },
        )
        self._session.flush()
        return PatronReviewDecisionResult(
            action="undo",
            product_id=product.id,
            stats=self.stats(),
        )

    def _count(self, predicate: Any) -> int:
        return int(
            self._session.scalar(
                select(func.count()).select_from(SourceProduct).where(
                    SourceProduct.is_active.is_(True),
                    predicate,
                )
            )
            or 0
        )

    def _is_remaining_product(self, product_id: int) -> bool:
        statement = select(SourceProduct.id).where(
            SourceProduct.id == product_id,
            SourceProduct.is_active.is_(True),
            self._remaining_predicate(),
        )
        return self._session.scalar(statement) is not None

    def _next_item(self) -> PatronReviewItem | None:
        latest_prices = latest_price_subquery()
        statement = (
            select(
                SourceProduct,
                Shop,
                Category,
                latest_prices.c.latest_price,
                latest_prices.c.latest_price_kind,
                latest_prices.c.latest_currency,
                latest_prices.c.latest_unit_raw,
                latest_prices.c.latest_source_updated_at,
                latest_prices.c.latest_parsed_at,
            )
            .join(Shop, Shop.id == SourceProduct.shop_id)
            .outerjoin(Category, Category.id == SourceProduct.category_id)
            .outerjoin(
                latest_prices,
                and_(
                    latest_prices.c.source_product_id == SourceProduct.id,
                    latest_prices.c.row_number == 1,
                ),
            )
            .where(SourceProduct.is_active.is_(True), self._remaining_predicate())
            .order_by(*self._order_by())
            .limit(1)
        )
        row = self._session.execute(statement).one_or_none()
        if row is None:
            return None
        (
            product,
            shop,
            category,
            latest_price,
            latest_price_kind,
            latest_currency,
            latest_unit_raw,
            latest_source_updated_at,
            latest_parsed_at,
        ) = row
        return _item(
            product=product,
            shop=shop,
            category=category,
            latest_price=latest_price,
            latest_price_kind=latest_price_kind,
            latest_currency=latest_currency,
            latest_unit_raw=latest_unit_raw,
            latest_source_updated_at=latest_source_updated_at,
            latest_parsed_at=latest_parsed_at,
        )

    def _last_review_decision(self, *, actor: str | None) -> OperatorDecision | None:
        undone_decision_ids = self._undone_review_decision_ids()
        statement = (
            select(OperatorDecision)
            .where(
                OperatorDecision.decision_type == "data_quality",
                OperatorDecision.action.in_(_REVIEW_ACTIONS),
            )
            .order_by(OperatorDecision.decided_at.desc(), OperatorDecision.id.desc())
        )
        if actor is not None:
            statement = statement.where(OperatorDecision.actor == actor)
        for decision in self._session.scalars(statement):
            if not self._decision_matches_mode(decision):
                continue
            if decision.id not in undone_decision_ids:
                return decision
        return None

    def _remaining_predicate(self) -> Any:
        if self._mode == "patron_rejected":
            return _patron_rejected_predicate(min_probability=self._min_probability)
        return _needs_review_predicate()

    def _review_mode_predicate(self) -> Any:
        review_queue = SourceProduct.raw["operator_review"]["patron_review"]["queue"].astext
        if self._mode == "needs_review":
            return or_(
                review_queue == "needs_review",
                review_queue.is_(None),
                review_queue == "",
            )
        return and_(
            review_queue == self._mode,
            _review_not_product_probability() >= self._min_probability,
        )

    def _order_by(self) -> tuple[Any, ...]:
        if self._mode == "patron_rejected":
            return (
                _not_product_probability().asc(),
                SourceProduct.last_seen_at.desc(),
                SourceProduct.id.asc(),
            )
        return (SourceProduct.last_seen_at.desc(), SourceProduct.id.asc())

    def _undone_review_decision_ids(self) -> set[int]:
        statement = select(OperatorDecision.evidence).where(
            OperatorDecision.decision_type == "data_quality",
            OperatorDecision.action == "patron_review_undo",
        )
        undone_ids: set[int] = set()
        for evidence in self._session.scalars(statement):
            if not isinstance(evidence, dict):
                continue
            value = evidence.get("undone_decision_id")
            if isinstance(value, int):
                undone_ids.add(value)
            elif isinstance(value, str) and value.isdecimal():
                undone_ids.add(int(value))
        return undone_ids

    def _decision_matches_mode(self, decision: OperatorDecision) -> bool:
        evidence = decision.evidence if isinstance(decision.evidence, dict) else {}
        queue = evidence.get("queue")
        if self._mode == "needs_review":
            return queue in (None, "", "needs_review")
        return queue == self._mode


def _needs_review_predicate() -> Any:
    return and_(
        SourceProduct.is_not_product.is_(False),
        SourceProduct.raw["catalog_eligibility"]["status"].astext == "needs_review",
        SourceProduct.raw["catalog_eligibility"]["method"].astext == "patron",
        or_(
            _review_status().is_(None),
            _review_status() == "",
        ),
    )


def _patron_rejected_predicate(*, min_probability: Decimal) -> Any:
    return and_(
        SourceProduct.is_not_product.is_(True),
        SourceProduct.raw["catalog_eligibility"]["status"].astext == "ineligible",
        SourceProduct.raw["catalog_eligibility"]["method"].astext == "patron",
        SourceProduct.raw["catalog_eligibility"]["reasons"].contains(["patron_not_product"]),
        _not_product_probability() >= min_probability,
        or_(
            _review_status().is_(None),
            _review_status() == "",
        ),
    )


def _mode_for_product(product: SourceProduct) -> PatronReviewMode | None:
    raw = product.raw or {}
    eligibility = raw.get("catalog_eligibility")
    if not isinstance(eligibility, dict):
        return None
    if eligibility.get("status") == "needs_review" and eligibility.get("method") == "patron":
        return "needs_review"
    reasons = eligibility.get("reasons")
    if (
        eligibility.get("status") == "ineligible"
        and eligibility.get("method") == "patron"
        and isinstance(reasons, list)
        and "patron_not_product" in reasons
    ):
        return "patron_rejected"
    return None


def _not_product_probability() -> Any:
    return cast(
        SourceProduct.raw["catalog_eligibility"]["not_product_probability"].astext,
        Numeric(5, 3),
    )


def _review_not_product_probability() -> Any:
    return cast(
        SourceProduct.raw["operator_review"]["patron_review"]["catalog_eligibility"][
            "not_product_probability"
        ].astext,
        Numeric(5, 3),
    )


def _review_status() -> Any:
    return SourceProduct.raw["operator_review"]["patron_review"]["status"].astext


def _item(
    *,
    product: SourceProduct,
    shop: Shop,
    category: Category | None,
    latest_price: Decimal | None,
    latest_price_kind: str | None,
    latest_currency: str | None,
    latest_unit_raw: str | None,
    latest_source_updated_at: datetime | None,
    latest_parsed_at: datetime | None,
) -> PatronReviewItem:
    latest = None
    if latest_parsed_at is not None:
        price_kind = latest_price_kind or "exact"
        currency = latest_currency or "RUB"
        latest = PatronReviewLatestPrice(
            price=latest_price,
            price_kind=price_kind,
            price_text=format_price_text(
                price=latest_price,
                currency=currency,
                price_kind=price_kind,
            ),
            currency=currency,
            unit_raw=latest_unit_raw,
            source_updated_at=latest_source_updated_at,
            parsed_at=latest_parsed_at,
        )
    return PatronReviewItem(
        id=product.id,
        source=product.source,
        source_product_id=product.source_product_id,
        title=product.title,
        normalized_title=product.normalized_title,
        description=product.description,
        category_id=product.category_id,
        category=(
            PatronReviewCategory(
                id=category.id,
                slug=category.slug,
                name=category.name,
            )
            if category is not None
            else None
        ),
        category_raw=product.category_raw,
        unit_raw=product.unit_raw,
        image_url=product.image_url,
        source_updated_at=product.source_updated_at,
        last_seen_at=product.last_seen_at,
        is_not_product=product.is_not_product,
        shop=PatronReviewShop(
            id=shop.id,
            source=shop.source,
            source_id=shop.source_id,
            name=shop.name,
        ),
        latest_price=latest,
        catalog_eligibility=_dict_value((product.raw or {}).get("catalog_eligibility")),
        raw=product.raw,
    )


def _raw_with_patron_review(
    raw: JsonObject | None,
    *,
    action: PatronReviewAction,
    actor: str | None,
    reason: str | None,
    queue: PatronReviewMode,
    reviewed_at: datetime,
) -> JsonObject:
    updated = dict(raw or {})
    operator_review = _dict_value(updated.get("operator_review")) or {}
    original_catalog_eligibility = _dict_value(updated.get("catalog_eligibility"))
    operator_review["patron_review"] = {
        "status": action,
        "queue": queue,
        "actor": actor,
        "reason": reason,
        "reviewed_at": reviewed_at.isoformat(),
    }
    if original_catalog_eligibility is not None:
        operator_review["patron_review"]["catalog_eligibility"] = original_catalog_eligibility
    if action in {"product", "not_product"}:
        is_not_product = action == "not_product"
        operator_review["data_problem"] = {
            "marked": is_not_product,
            "reason": reason,
            "actor": actor,
            "reviewed_at": reviewed_at.isoformat(),
        }
        updated["catalog_eligibility"] = {
            "status": "ineligible" if is_not_product else "eligible",
            "confidence": "1.000",
            "score": 0 if is_not_product else 100,
            "reasons": [f"patron_review_{action}"],
            "method": "operator_review",
        }
    updated["operator_review"] = operator_review
    return updated


def _product_state(product: SourceProduct) -> JsonObject:
    raw = dict(product.raw or {})
    return {
        "is_not_product": product.is_not_product,
        "raw": raw,
        "catalog_eligibility": raw.get("catalog_eligibility"),
        "operator_review": raw.get("operator_review"),
    }


def _dict_value(value: object) -> JsonObject | None:
    return dict(value) if isinstance(value, dict) else None
