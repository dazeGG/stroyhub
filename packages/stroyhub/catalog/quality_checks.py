from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from stroyhub.catalog.attributes import ExtractedAttribute, extract_product_attributes
from stroyhub.catalog.query_helpers import latest_price_subquery
from stroyhub.models.tables import CanonicalProduct, Category, ProductMatch, Shop, SourceProduct
from stroyhub.parsers.common import JsonObject

CatalogQualitySeverity = Literal["blocker", "warning"]


@dataclass(frozen=True, kw_only=True)
class CatalogQualityCheckFilters:
    severity: CatalogQualitySeverity | None = None
    code: str | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, kw_only=True)
class CatalogQualityFinding:
    code: str
    severity: CatalogQualitySeverity
    reason: str
    recommended_action: str
    source_product_id: int | None = None
    canonical_product_id: int | None = None
    shop_id: int | None = None
    related_source_product_ids: tuple[int, ...] = ()
    related_canonical_product_ids: tuple[int, ...] = ()
    metadata: JsonObject | None = None


@dataclass(frozen=True, kw_only=True)
class CatalogQualityFindingPage:
    items: tuple[CatalogQualityFinding, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, kw_only=True)
class CatalogQualityCheckSummary:
    total: int
    blockers: int
    warnings: int
    by_code: dict[str, int]


@dataclass(frozen=True, kw_only=True)
class CatalogQualityCheckReport:
    summary: CatalogQualityCheckSummary
    findings: CatalogQualityFindingPage


class CatalogQualityCheckService:
    def __init__(
        self,
        session: Session,
        *,
        now: datetime | None = None,
        stale_price_after_days: int = 30,
        stale_shop_after_days: int = 7,
        low_category_confidence: Decimal = Decimal("0.750"),
    ) -> None:
        self._session = session
        self._now = now or datetime.now(UTC)
        self._stale_price_cutoff = self._now - timedelta(days=stale_price_after_days)
        self._stale_shop_cutoff = self._now - timedelta(days=stale_shop_after_days)
        self._low_category_confidence = low_category_confidence

    def report(
        self,
        filters: CatalogQualityCheckFilters | None = None,
    ) -> CatalogQualityCheckReport:
        selected_filters = filters or CatalogQualityCheckFilters()
        findings = self._filtered_findings(selected_filters)
        page_items = tuple(
            findings[selected_filters.offset:selected_filters.offset + selected_filters.limit]
        )
        by_code: dict[str, int] = defaultdict(int)
        blockers = 0
        warnings = 0
        for finding in findings:
            by_code[finding.code] += 1
            if finding.severity == "blocker":
                blockers += 1
            else:
                warnings += 1

        return CatalogQualityCheckReport(
            summary=CatalogQualityCheckSummary(
                total=len(findings),
                blockers=blockers,
                warnings=warnings,
                by_code=dict(sorted(by_code.items())),
            ),
            findings=CatalogQualityFindingPage(
                items=page_items,
                total=len(findings),
                limit=selected_filters.limit,
                offset=selected_filters.offset,
            ),
        )

    def _filtered_findings(
        self,
        filters: CatalogQualityCheckFilters,
    ) -> tuple[CatalogQualityFinding, ...]:
        findings = [
            *self._duplicate_canonical_findings(),
            *self._accepted_attribute_conflict_findings(),
            *self._stale_price_findings(),
            *self._stale_shop_findings(),
            *self._missing_attribute_findings(),
            *self._category_quality_findings(),
        ]
        if filters.severity is not None:
            findings = [finding for finding in findings if finding.severity == filters.severity]
        if filters.code is not None:
            findings = [finding for finding in findings if finding.code == filters.code]
        return tuple(sorted(findings, key=_finding_sort_key))

    def _duplicate_canonical_findings(self) -> list[CatalogQualityFinding]:
        products = list(
            self._session.scalars(
                select(CanonicalProduct)
                .where(CanonicalProduct.match_status == "active")
                .order_by(CanonicalProduct.id.asc())
            )
        )
        groups: dict[tuple[str, int | None], list[CanonicalProduct]] = defaultdict(list)
        for product in products:
            title_key = product.normalized_title.strip()
            if title_key:
                groups[(title_key, product.category_id)].append(product)

        findings: list[CatalogQualityFinding] = []
        for (normalized_title, category_id), group in groups.items():
            if len(group) < 2:
                continue
            canonical_ids = tuple(product.id for product in group)
            findings.append(
                CatalogQualityFinding(
                    code="duplicate_normalized_product",
                    severity="warning",
                    reason=(
                        "Several active normalized products share the same normalized title "
                        "and category."
                    ),
                    recommended_action=(
                        "Merge or deactivate duplicate normalized products before public use."
                    ),
                    canonical_product_id=canonical_ids[0],
                    related_canonical_product_ids=canonical_ids,
                    metadata={
                        "normalized_title": normalized_title,
                        "category_id": category_id,
                        "titles": [product.title for product in group],
                    },
                )
            )
        return findings

    def _accepted_attribute_conflict_findings(self) -> list[CatalogQualityFinding]:
        rows = self._session.execute(
            select(ProductMatch, SourceProduct, CanonicalProduct)
            .join(SourceProduct, ProductMatch.source_product_id == SourceProduct.id)
            .join(CanonicalProduct, ProductMatch.canonical_product_id == CanonicalProduct.id)
            .where(
                ProductMatch.status == "accepted",
                SourceProduct.is_active.is_(True),
                SourceProduct.is_not_product.is_(False),
                CanonicalProduct.match_status == "active",
            )
            .order_by(ProductMatch.id.asc())
        )
        findings: list[CatalogQualityFinding] = []
        for match, source_product, canonical_product in rows:
            conflicts = _attribute_conflicts(
                extract_product_attributes(
                    source_product.title,
                    source=source_product.source,
                    category_raw=source_product.category_raw,
                ).attributes,
                extract_product_attributes(canonical_product.title).attributes,
            )
            if not conflicts:
                continue
            findings.append(
                CatalogQualityFinding(
                    code="accepted_attribute_conflict",
                    severity="blocker",
                    reason=(
                        "Accepted offer has protected attributes that conflict with the "
                        "normalized product."
                    ),
                    recommended_action=(
                        "Review the accepted link; reject or move the offer to the correct "
                        "normalized product."
                    ),
                    source_product_id=source_product.id,
                    canonical_product_id=canonical_product.id,
                    shop_id=source_product.shop_id,
                    related_source_product_ids=(source_product.id,),
                    related_canonical_product_ids=(canonical_product.id,),
                    metadata={
                        "match_id": match.id,
                        "source_title": source_product.title,
                        "canonical_title": canonical_product.title,
                        "conflicts": conflicts,
                    },
                )
            )
        return findings

    def _stale_price_findings(self) -> list[CatalogQualityFinding]:
        latest_prices = latest_price_subquery()
        rows = self._session.execute(
            select(SourceProduct, latest_prices.c.latest_parsed_at)
            .outerjoin(
                latest_prices,
                and_(
                    latest_prices.c.source_product_id == SourceProduct.id,
                    latest_prices.c.row_number == 1,
                ),
            )
            .where(SourceProduct.is_active.is_(True), SourceProduct.is_not_product.is_(False))
            .order_by(SourceProduct.id.asc())
        )

        findings: list[CatalogQualityFinding] = []
        for product, latest_parsed_at in rows:
            if latest_parsed_at is None:
                findings.append(
                    CatalogQualityFinding(
                        code="missing_price_snapshot",
                        severity="blocker",
                        reason="Source product has no price observations.",
                        recommended_action=(
                            "Scrape the source again or exclude the card from the public catalog."
                        ),
                        source_product_id=product.id,
                        shop_id=product.shop_id,
                        related_source_product_ids=(product.id,),
                    )
                )
            elif latest_parsed_at < self._stale_price_cutoff:
                findings.append(
                    CatalogQualityFinding(
                        code="stale_price",
                        severity="warning",
                        reason="Latest price observation is older than the freshness threshold.",
                        recommended_action=(
                            "Rescrape the source and verify the offer is still available."
                        ),
                        source_product_id=product.id,
                        shop_id=product.shop_id,
                        related_source_product_ids=(product.id,),
                        metadata={
                            "latest_parsed_at": latest_parsed_at.isoformat(),
                            "stale_before": self._stale_price_cutoff.isoformat(),
                        },
                    )
                )
        return findings

    def _stale_shop_findings(self) -> list[CatalogQualityFinding]:
        shops = self._session.scalars(
            select(Shop)
            .where(Shop.scrape_status != "disabled")
            .order_by(Shop.id.asc())
        )
        findings: list[CatalogQualityFinding] = []
        for shop in shops:
            if shop.last_scraped_at is None:
                findings.append(
                    CatalogQualityFinding(
                        code="shop_never_scraped",
                        severity="warning",
                        reason="Shop has not been scraped yet.",
                        recommended_action=(
                            "Schedule the shop scrape before using its offers publicly."
                        ),
                        shop_id=shop.id,
                    )
                )
            elif shop.last_scraped_at < self._stale_shop_cutoff:
                findings.append(
                    CatalogQualityFinding(
                        code="stale_shop",
                        severity="warning",
                        reason="Shop scrape is older than the freshness threshold.",
                        recommended_action="Schedule a new scrape for the shop.",
                        shop_id=shop.id,
                        metadata={
                            "last_scraped_at": shop.last_scraped_at.isoformat(),
                            "stale_before": self._stale_shop_cutoff.isoformat(),
                        },
                    )
                )
        return findings

    def _missing_attribute_findings(self) -> list[CatalogQualityFinding]:
        rows = self._session.execute(
            select(SourceProduct, Category)
            .join(Category, SourceProduct.category_id == Category.id)
            .where(SourceProduct.is_active.is_(True), SourceProduct.is_not_product.is_(False))
            .order_by(SourceProduct.id.asc())
        )
        findings: list[CatalogQualityFinding] = []
        for product, category in rows:
            extraction = extract_product_attributes(
                product.title,
                source=product.source,
                category_raw=product.category_raw,
            )
            if extraction.attributes:
                continue
            findings.append(
                CatalogQualityFinding(
                    code="missing_critical_attributes",
                    severity="warning",
                    reason=(
                        "Product has a normalized category but no protected attributes were "
                        "extracted."
                    ),
                    recommended_action=(
                        "Review the title/category or enrich parsing rules for this category."
                    ),
                    source_product_id=product.id,
                    shop_id=product.shop_id,
                    related_source_product_ids=(product.id,),
                    metadata={"category_id": category.id, "category_slug": category.slug},
                )
            )
        return findings

    def _category_quality_findings(self) -> list[CatalogQualityFinding]:
        products = self._session.scalars(
            select(SourceProduct)
            .where(SourceProduct.is_active.is_(True), SourceProduct.is_not_product.is_(False))
            .order_by(SourceProduct.id.asc())
        )
        findings: list[CatalogQualityFinding] = []
        for product in products:
            if product.category_id is None:
                findings.append(
                    CatalogQualityFinding(
                        code="uncategorized_product",
                        severity="warning",
                        reason="Source product has no normalized category.",
                        recommended_action=(
                            "Assign or map the category before public catalog exposure."
                        ),
                        source_product_id=product.id,
                        shop_id=product.shop_id,
                        related_source_product_ids=(product.id,),
                    )
                )
                continue

            confidence = _category_confidence(product.raw)
            if confidence is not None and confidence < self._low_category_confidence:
                findings.append(
                    CatalogQualityFinding(
                        code="low_confidence_category",
                        severity="warning",
                        reason="Category assignment confidence is below the readiness threshold.",
                        recommended_action="Review and confirm the product category.",
                        source_product_id=product.id,
                        shop_id=product.shop_id,
                        related_source_product_ids=(product.id,),
                        metadata={
                            "confidence": str(confidence),
                            "threshold": str(self._low_category_confidence),
                        },
                    )
                )
        return findings


def _finding_sort_key(finding: CatalogQualityFinding) -> tuple[int, str, int, int, int]:
    severity_rank = 0 if finding.severity == "blocker" else 1
    return (
        severity_rank,
        finding.code,
        finding.shop_id or 0,
        finding.source_product_id or 0,
        finding.canonical_product_id or 0,
    )


def _attribute_conflicts(
    source_attributes: tuple[ExtractedAttribute, ...],
    canonical_attributes: tuple[ExtractedAttribute, ...],
) -> list[JsonObject]:
    source = _attribute_values_by_kind(source_attributes)
    canonical = _attribute_values_by_kind(canonical_attributes)
    conflicts: list[JsonObject] = []
    for kind in sorted(source.keys() & canonical.keys()):
        source_values = source[kind]
        canonical_values = canonical[kind]
        if source_values and canonical_values and source_values.isdisjoint(canonical_values):
            conflicts.append(
                {
                    "kind": kind,
                    "source_values": sorted(source_values),
                    "canonical_values": sorted(canonical_values),
                }
            )
    return conflicts


def _attribute_values_by_kind(
    attributes: tuple[ExtractedAttribute, ...],
) -> dict[str, set[str]]:
    values_by_kind: dict[str, set[str]] = defaultdict(set)
    for attribute in attributes:
        values_by_kind[attribute.kind].add(_attribute_signature(attribute))
    return values_by_kind


def _attribute_signature(attribute: ExtractedAttribute) -> str:
    if attribute.values:
        values = ",".join(str(value.normalize()) for value in attribute.values)
        return f"{values}:{attribute.unit}"
    if attribute.normalized:
        return attribute.normalized
    return attribute.raw.strip().lower()


def _category_confidence(raw: JsonObject | None) -> Decimal | None:
    if not raw:
        return None
    quality = raw.get("catalog_quality")
    if not isinstance(quality, dict):
        return None
    categorization = quality.get("categorization")
    if not isinstance(categorization, dict):
        return None
    value = categorization.get("confidence")
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None
