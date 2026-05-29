from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from stroyhub.catalog.eligibility import (
    CatalogEligibilityStatus,
    ProductEligibility,
    ProductEligibilityInput,
    evaluate_product_eligibility,
    evaluate_product_hard_constraints,
    operator_data_problem_mark,
)
from stroyhub.catalog.products import format_price_text
from stroyhub.ml.not_product_classifier import (
    NotProductClassifierModelUnavailableError,
    NotProductClassifierResult,
    PatronClassifier,
)
from stroyhub.models import SourceProduct
from stroyhub.parsers.common import JsonObject, ParsedProduct

_DECIMAL_QUANT = Decimal("0.001")
logger = logging.getLogger(__name__)


class PatronClassifierLike(Protocol):
    def predict_record(self, record: dict[str, Any]) -> NotProductClassifierResult:
        pass


@dataclass(frozen=True, kw_only=True)
class ProductSuitabilityEvaluator:
    patron: PatronClassifierLike | None = None

    @classmethod
    def default(
        cls,
        *,
        root: Path | None = None,
        model_dir: str | Path | None = None,
        require_patron: bool = False,
    ) -> ProductSuitabilityEvaluator:
        try:
            patron = PatronClassifier.default(root=root, model_dir=model_dir)
        except NotProductClassifierModelUnavailableError:
            if require_patron:
                raise
            logger.warning("Patron model is unavailable; falling back to suitability rules")
            patron = None
        return cls(patron=patron)

    def evaluate(
        self,
        product: ParsedProduct,
        *,
        existing_product: SourceProduct | None = None,
        shop_name: str | None = None,
        shop_url: str | None = None,
        category_name: str | None = None,
        category_path: Sequence[str] = (),
    ) -> ProductEligibility:
        operator_mark = operator_data_problem_mark(
            existing_product.raw if existing_product is not None else None
        )
        if operator_mark is not None:
            return _operator_decision(operator_mark)

        eligibility_input = ProductEligibilityInput(
            source=product.source,
            title=product.title,
            price=product.price,
            raw=product.raw,
            price_kind=product.price_kind,
        )
        hard_decision = evaluate_product_hard_constraints(eligibility_input)
        if hard_decision is not None:
            return hard_decision

        if self.patron is None:
            return evaluate_product_eligibility(eligibility_input)

        prediction = self.patron.predict_record(
            _patron_record(
                product,
                shop_name=shop_name,
                shop_url=shop_url,
                category_name=category_name,
                category_path=category_path,
            )
        )
        return _patron_decision(prediction)


def _operator_decision(marked: bool) -> ProductEligibility:
    return ProductEligibility(
        status="ineligible" if marked else "eligible",
        confidence=Decimal("1.000"),
        reasons=("operator_data_problem",),
        score=0 if marked else 100,
        method="operator_review",
    )


def _patron_decision(prediction: NotProductClassifierResult) -> ProductEligibility:
    not_product_probability = _decimal(prediction.not_product_probability)
    not_product_threshold = _decimal(prediction.threshold)
    product_threshold = Decimal("1") - not_product_threshold
    confidence = max(not_product_probability, Decimal("1") - not_product_probability)

    if not_product_probability >= not_product_threshold:
        status: CatalogEligibilityStatus = "ineligible"
        reasons = ("patron_not_product",)
        score = 0
    elif not_product_probability <= product_threshold:
        status = "eligible"
        reasons = ("patron_product",)
        score = 100
    else:
        status = "needs_review"
        reasons = ("patron_uncertain",)
        score = int(confidence * 100)

    return ProductEligibility(
        status=status,
        confidence=confidence.quantize(_DECIMAL_QUANT),
        reasons=reasons,
        score=score,
        method="patron",
        model_name=prediction.model_name,
        model_version=prediction.model_version,
        feature_schema_version=prediction.feature_schema_version,
        not_product_probability=not_product_probability,
        thresholds={
            "not_product": str(not_product_threshold),
            "product": str(product_threshold),
        },
    )


def _patron_record(
    product: ParsedProduct,
    *,
    shop_name: str | None,
    shop_url: str | None,
    category_name: str | None,
    category_path: Sequence[str],
) -> JsonObject:
    return {
        "source": product.source,
        "shop": {
            "name": shop_name,
            "url": shop_url,
        },
        "product": {
            "title": product.title,
            "normalized_title": product.normalized_title,
            "description": product.description,
            "category_raw": product.category_raw,
            "category_name": category_name,
            "category_path": list(category_path),
            "unit_raw": product.unit_raw,
            "image_url": product.image_url,
        },
        "latest_price": {
            "price": str(product.price) if product.price is not None else None,
            "currency": product.currency,
            "unit_raw": product.unit_raw,
            "price_kind": product.price_kind,
            "price_text": format_price_text(
                price=product.price,
                currency=product.currency,
                price_kind=product.price_kind,
            ),
        },
    }


def _decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(_DECIMAL_QUANT)
