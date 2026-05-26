from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.catalog.product_match_generation import ProductMatchCandidateGenerator
from stroyhub.db.repositories import (
    CanonicalProductCreate,
    CanonicalProductRepository,
    JsonObject,
    ProductMatchCreate,
    ProductMatchRepository,
)
from stroyhub.models.tables import CanonicalProduct, ProductMatch, SourceProduct
from stroyhub.parsers.common import normalize_title


class ProductMatchDecisionError(Exception):
    pass


class ProductMatchDecisionNotFound(ProductMatchDecisionError):
    pass


class ProductMatchDecisionConflict(ProductMatchDecisionError):
    pass


@dataclass(frozen=True, kw_only=True)
class ProductMatchDecision:
    id: int
    canonical_product_id: int
    source_product_id: int
    confidence: Decimal
    status: str
    method: str
    matched_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None
    reason: JsonObject | None


@dataclass(frozen=True, kw_only=True)
class ProductMatchDecisionInput:
    actor: str | None = "admin"
    reason: str | None = None
    decision: JsonObject | None = None


class ProductMatchDecisionService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def accept_existing(
        self,
        *,
        canonical_product_id: int,
        source_product_id: int,
        data: ProductMatchDecisionInput,
    ) -> ProductMatchDecision:
        return self._accept(
            canonical_product_id=canonical_product_id,
            source_product_id=source_product_id,
            data=data,
            supersede_existing=False,
        )

    def supersede_existing(
        self,
        *,
        canonical_product_id: int,
        source_product_id: int,
        data: ProductMatchDecisionInput,
    ) -> ProductMatchDecision:
        return self._accept(
            canonical_product_id=canonical_product_id,
            source_product_id=source_product_id,
            data=data,
            supersede_existing=True,
        )

    def create_canonical_from_source_and_accept(
        self,
        *,
        source_product_id: int,
        data: ProductMatchDecisionInput,
    ) -> ProductMatchDecision:
        source_product = self._source_product(source_product_id)
        accepted = self._accepted_match(source_product_id)
        if accepted is not None:
            raise ProductMatchDecisionConflict(
                "Source product already has an accepted canonical match"
            )

        canonical = CanonicalProductRepository(self._session).create(
            CanonicalProductCreate(
                title=source_product.title,
                normalized_title=source_product.normalized_title
                or normalize_title(source_product.title),
                category_id=source_product.category_id,
                unit_raw=source_product.unit_raw,
            )
        )
        return self._create_or_accept_pair(
            canonical_product_id=canonical.id,
            source_product_id=source_product.id,
            data=data,
        )

    def reject_candidate(
        self,
        *,
        match_id: int,
        data: ProductMatchDecisionInput,
    ) -> ProductMatchDecision:
        match = ProductMatchRepository(self._session).get(match_id)
        if match is None:
            raise ProductMatchDecisionNotFound("Product match not found")
        if match.status == "rejected":
            return _decision(match)
        if match.status != "candidate":
            raise ProductMatchDecisionConflict("Only candidate matches can be rejected")

        reviewed_at = datetime.now(UTC)
        updated = ProductMatchRepository(self._session).update_status(
            match,
            status="rejected",
            reviewed_at=reviewed_at,
            reviewed_by=data.actor,
            reason=_decision_reason(data, action="reject"),
        )
        return _decision(updated)

    def _accept(
        self,
        *,
        canonical_product_id: int,
        source_product_id: int,
        data: ProductMatchDecisionInput,
        supersede_existing: bool,
    ) -> ProductMatchDecision:
        self._canonical_product(canonical_product_id)
        self._source_product(source_product_id)

        accepted = self._accepted_match(source_product_id)
        if accepted is not None:
            if accepted.canonical_product_id == canonical_product_id:
                return _decision(accepted)
            if not supersede_existing:
                raise ProductMatchDecisionConflict(
                    "Source product already has an accepted canonical match"
                )
            ProductMatchRepository(self._session).update_status(
                accepted,
                status="superseded",
                reviewed_at=datetime.now(UTC),
                reviewed_by=data.actor,
                reason=_decision_reason(data, action="supersede"),
            )

        return self._create_or_accept_pair(
            canonical_product_id=canonical_product_id,
            source_product_id=source_product_id,
            data=data,
        )

    def _create_or_accept_pair(
        self,
        *,
        canonical_product_id: int,
        source_product_id: int,
        data: ProductMatchDecisionInput,
    ) -> ProductMatchDecision:
        existing = self._match_for_pair(
            canonical_product_id=canonical_product_id,
            source_product_id=source_product_id,
        )
        reviewed_at = datetime.now(UTC)
        if existing is not None:
            existing.confidence = Decimal("1.000")
            existing.method = "manual"
            updated = ProductMatchRepository(self._session).update_status(
                existing,
                status="accepted",
                reviewed_at=reviewed_at,
                reviewed_by=data.actor,
                reason=_decision_reason(data, action="accept"),
            )
            self._generate_followup_candidates(canonical_product_id)
            return _decision(updated)

        match = ProductMatchRepository(self._session).create(
            ProductMatchCreate(
                canonical_product_id=canonical_product_id,
                source_product_id=source_product_id,
                confidence=Decimal("1.000"),
                method="manual",
                status="accepted",
                reviewed_at=reviewed_at,
                reviewed_by=data.actor,
                reason=_decision_reason(data, action="accept"),
            )
        )
        self._generate_followup_candidates(canonical_product_id)
        return _decision(match)

    def _canonical_product(self, canonical_product_id: int) -> CanonicalProduct:
        product = self._session.get(CanonicalProduct, canonical_product_id)
        if product is None:
            raise ProductMatchDecisionNotFound("Canonical product not found")
        return product

    def _source_product(self, source_product_id: int) -> SourceProduct:
        product = self._session.get(SourceProduct, source_product_id)
        if product is None:
            raise ProductMatchDecisionNotFound("Source product not found")
        return product

    def _accepted_match(self, source_product_id: int) -> ProductMatch | None:
        return self._session.scalar(
            select(ProductMatch).where(
                ProductMatch.source_product_id == source_product_id,
                ProductMatch.status == "accepted",
            )
        )

    def _match_for_pair(
        self,
        *,
        canonical_product_id: int,
        source_product_id: int,
    ) -> ProductMatch | None:
        return self._session.scalar(
            select(ProductMatch).where(
                ProductMatch.canonical_product_id == canonical_product_id,
                ProductMatch.source_product_id == source_product_id,
            )
        )

    def _generate_followup_candidates(self, canonical_product_id: int) -> None:
        ProductMatchCandidateGenerator(self._session).generate_for_canonical(
            canonical_product_id
        )


def _decision(match: ProductMatch) -> ProductMatchDecision:
    return ProductMatchDecision(
        id=match.id,
        canonical_product_id=match.canonical_product_id,
        source_product_id=match.source_product_id,
        confidence=match.confidence,
        status=match.status,
        method=match.method,
        matched_at=match.matched_at,
        reviewed_at=match.reviewed_at,
        reviewed_by=match.reviewed_by,
        reason=match.reason,
    )


def _decision_reason(
    data: ProductMatchDecisionInput,
    *,
    action: str,
) -> JsonObject:
    reason: JsonObject = {"action": action}
    if data.reason is not None:
        reason["note"] = data.reason
    if data.decision is not None:
        reason["decision"] = data.decision
    return reason
