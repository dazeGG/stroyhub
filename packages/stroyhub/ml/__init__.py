"""Classification and matching experiments."""

from stroyhub.ml.labels import (
    CategoryLabelRecord,
    CategoryLabelStore,
    PredictorTarget,
    VerifierPairLabel,
)
from stroyhub.ml.matching import (
    MatchProduct,
    ProductMatchCandidate,
    ProductMatchReason,
    SourceProductLike,
    generate_product_match_candidates,
)

__all__ = [
    "MatchProduct",
    "ProductMatchCandidate",
    "ProductMatchReason",
    "CategoryLabelRecord",
    "CategoryLabelStore",
    "PredictorTarget",
    "SourceProductLike",
    "VerifierPairLabel",
    "generate_product_match_candidates",
]
