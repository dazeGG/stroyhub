"""Classification and matching experiments."""

from stroyhub.ml.category_queue import (
    CategoryLabelCandidate,
    CategoryLabelProduct,
    CategoryLabelQueue,
    CategoryLabelQueueItem,
)
from stroyhub.ml.datasets import (
    CategoryVerifierDatasetStatus,
    CategoryVerifierDatasetStore,
    CategoryVerifierSnapshot,
    CategoryVerifierSnapshotMetadata,
)
from stroyhub.ml.features import (
    CATEGORY_VERIFIER_FEATURE_SCHEMA_VERSION,
    CategoryVerifierCategoryInput,
    CategoryVerifierFeatureRow,
    CategoryVerifierProductInput,
    build_category_verifier_features,
)
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
from stroyhub.ml.operator_decisions import (
    CategoryDecisionExample,
    CategoryPrediction,
    CategoryPredictionMetrics,
    NormalizationDecisionExample,
    NormalizationPrediction,
    NormalizationPredictionMetrics,
    OperatorDecisionDatasetBuilder,
    evaluate_category_predictions,
    evaluate_normalization_predictions,
    export_operator_decisions_jsonl,
)
from stroyhub.ml.runtime import (
    CategoryVerifier,
    CategoryVerifierModelUnavailableError,
    CategoryVerifierResult,
    CategoryVerifierThresholds,
)
from stroyhub.ml.training import (
    CategoryVerifierTrainingResult,
    InsufficientTrainingDataError,
    require_training_ready,
    train_category_verifier_from_snapshot,
)
from stroyhub.ml.verifier import (
    CategoryVerifierBaselineModel,
    CategoryVerifierExample,
    CategoryVerifierPrediction,
)

__all__ = [
    "MatchProduct",
    "ProductMatchCandidate",
    "ProductMatchReason",
    "CategoryLabelRecord",
    "CategoryLabelCandidate",
    "CategoryLabelProduct",
    "CategoryLabelQueue",
    "CategoryLabelQueueItem",
    "CategoryLabelStore",
    "CategoryDecisionExample",
    "CategoryPrediction",
    "CategoryPredictionMetrics",
    "CategoryVerifierDatasetStatus",
    "CategoryVerifierDatasetStore",
    "CategoryVerifierCategoryInput",
    "CategoryVerifierFeatureRow",
    "CategoryVerifierProductInput",
    "CategoryVerifierBaselineModel",
    "CategoryVerifierExample",
    "CategoryVerifier",
    "CategoryVerifierModelUnavailableError",
    "CategoryVerifierPrediction",
    "CategoryVerifierResult",
    "CategoryVerifierSnapshot",
    "CategoryVerifierSnapshotMetadata",
    "CategoryVerifierThresholds",
    "CategoryVerifierTrainingResult",
    "CATEGORY_VERIFIER_FEATURE_SCHEMA_VERSION",
    "InsufficientTrainingDataError",
    "NormalizationDecisionExample",
    "NormalizationPrediction",
    "NormalizationPredictionMetrics",
    "OperatorDecisionDatasetBuilder",
    "PredictorTarget",
    "SourceProductLike",
    "VerifierPairLabel",
    "build_category_verifier_features",
    "evaluate_category_predictions",
    "evaluate_normalization_predictions",
    "export_operator_decisions_jsonl",
    "generate_product_match_candidates",
    "require_training_ready",
    "train_category_verifier_from_snapshot",
]
