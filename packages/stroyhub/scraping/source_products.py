from __future__ import annotations

from dataclasses import dataclass, replace

from stroyhub.catalog.eligibility import with_catalog_eligibility
from stroyhub.catalog.product_suitability import ProductSuitabilityEvaluator
from stroyhub.db.repositories import (
    PriceSnapshotCreate,
    PriceSnapshotRepository,
    SourceProductRepository,
    SourceProductUpsert,
)
from stroyhub.models import PriceSnapshot, SourceProduct
from stroyhub.parsers.common import ParsedProduct


@dataclass(frozen=True, kw_only=True)
class PersistedSourceProductObservation:
    source_product: SourceProduct
    price_snapshot: PriceSnapshot


def persist_source_product_observation(
    *,
    product_repository: SourceProductRepository,
    price_repository: PriceSnapshotRepository,
    suitability_evaluator: ProductSuitabilityEvaluator,
    shop_id: int,
    product: ParsedProduct,
    category_id: int | None,
) -> PersistedSourceProductObservation:
    upsert = SourceProductUpsert(
        shop_id=shop_id,
        source=product.source,
        source_product_id=product.source_product_id,
        fingerprint=product.fingerprint,
        title=product.title,
        normalized_title=product.normalized_title,
        description=product.description,
        category_id=category_id,
        category_raw=product.category_raw,
        unit_raw=product.unit_raw,
        image_url=product.image_url,
        source_updated_at=product.source_updated_at,
        raw=product.raw,
        observed_at=product.parsed_at,
    )
    existing_product = product_repository.get_for_upsert(upsert)
    suitability = suitability_evaluator.evaluate(
        product,
        existing_product=existing_product,
    )
    source_product = product_repository.upsert(
        replace(
            upsert,
            raw=with_catalog_eligibility(
                product.raw,
                suitability,
                existing_raw=existing_product.raw if existing_product is not None else None,
            ),
            is_not_product=suitability.is_not_product,
        )
    )
    price_snapshot = price_repository.add(
        PriceSnapshotCreate(
            source_product_id=source_product.id,
            price=product.price,
            price_kind=product.price_kind,
            currency=product.currency,
            unit_raw=product.unit_raw,
            source_updated_at=product.source_updated_at,
            parsed_at=product.parsed_at,
            raw=product.raw,
        )
    )
    return PersistedSourceProductObservation(
        source_product=source_product,
        price_snapshot=price_snapshot,
    )
