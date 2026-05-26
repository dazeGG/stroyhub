from datetime import UTC, datetime

from stroyhub.ml.operator_decisions import (
    CategoryDecisionExample,
    CategoryPrediction,
    NormalizationDecisionExample,
    NormalizationPrediction,
    evaluate_category_predictions,
    evaluate_normalization_predictions,
)


def test_category_prediction_metrics_report_top_n_accuracy() -> None:
    labels = [
        _category_label(source_product_id=1, category_id=10),
        _category_label(source_product_id=2, category_id=20),
        _category_label(source_product_id=3, category_id=30),
    ]
    predictions = [
        CategoryPrediction(source_product_id=1, ranked_category_ids=(10, 11, 12)),
        CategoryPrediction(source_product_id=2, ranked_category_ids=(21, 20, 22)),
    ]

    metrics = evaluate_category_predictions(labels, predictions, top_n=2)

    assert metrics.label_count == 3
    assert metrics.prediction_count == 2
    assert metrics.missing_prediction_count == 1
    assert metrics.top_1_accuracy == 1 / 3
    assert metrics.top_n_accuracy == 2 / 3


def test_normalization_prediction_metrics_report_precision_recall_and_unsafe_auto_accept() -> None:
    labels = [
        _normalization_label(
            source_product_id=1,
            canonical_product_id=10,
            outcome="accepted",
        ),
        _normalization_label(
            source_product_id=2,
            canonical_product_id=20,
            outcome="rejected",
        ),
        _normalization_label(
            source_product_id=3,
            canonical_product_id=30,
            outcome="accepted",
        ),
    ]
    predictions = [
        NormalizationPrediction(
            source_product_id=1,
            canonical_product_id=10,
            decision="accept",
            auto_accept=True,
            safety_checks_passed=True,
            explanation={"blockers": []},
        ),
        NormalizationPrediction(
            source_product_id=2,
            canonical_product_id=20,
            decision="accept",
            auto_accept=True,
            safety_checks_passed=True,
            explanation={"blockers": []},
        ),
        NormalizationPrediction(
            source_product_id=3,
            canonical_product_id=30,
            decision="reject",
        ),
    ]

    metrics = evaluate_normalization_predictions(labels, predictions)

    assert metrics.label_count == 3
    assert metrics.prediction_count == 3
    assert metrics.precision == 0.5
    assert metrics.recall == 0.5
    assert metrics.auto_accept_count == 2
    assert metrics.unsafe_auto_accept_count == 1
    assert metrics.unsafe_auto_accept_rate == 0.5


def _category_label(*, source_product_id: int, category_id: int) -> CategoryDecisionExample:
    return CategoryDecisionExample(
        source_product_id=source_product_id,
        category_id=category_id,
        candidate_category_ids=(category_id,),
        actor="reviewer",
        decided_at=datetime(2026, 5, 26, tzinfo=UTC),
        evidence=None,
        alternatives=None,
    )


def _normalization_label(
    *,
    source_product_id: int,
    canonical_product_id: int,
    outcome: str,
) -> NormalizationDecisionExample:
    return NormalizationDecisionExample(
        source_product_id=source_product_id,
        canonical_product_id=canonical_product_id,
        product_match_id=None,
        outcome=outcome,
        action="attach_to_existing" if outcome == "accepted" else "reject_suggestion",
        actor="reviewer",
        decided_at=datetime(2026, 5, 26, tzinfo=UTC),
        evidence=None,
        alternatives=None,
    )
