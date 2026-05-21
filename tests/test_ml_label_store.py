from datetime import UTC, datetime

import pytest
from stroyhub.ml.labels import CategoryLabelRecord, CategoryLabelStore


def test_category_label_store_appends_and_reads_records(tmp_path) -> None:
    store = CategoryLabelStore(tmp_path / "labels.jsonl")
    labeled_at = datetime(2026, 5, 22, 1, 0, tzinfo=UTC)

    saved = store.append(
        CategoryLabelRecord(
            product_id=10,
            candidate_category_ids=(1, 2, 3),
            selected_category_ids=(2,),
            labeled_by="tester",
            labeled_at=labeled_at,
        )
    )

    assert saved.labeled_at == labeled_at
    assert store.read_records() == [saved]


def test_category_label_store_derives_verifier_pair_labels(tmp_path) -> None:
    store = CategoryLabelStore(tmp_path / "labels.jsonl")
    store.append(
        CategoryLabelRecord(
            product_id=10,
            candidate_category_ids=(1, 2, 3),
            selected_category_ids=(2,),
            labeled_by="tester",
            labeled_at=datetime(2026, 5, 22, 1, 0, tzinfo=UTC),
        )
    )

    labels = store.verifier_pair_labels()

    assert [(label.category_id, label.outcome) for label in labels] == [
        (1, "no_match"),
        (2, "match"),
        (3, "no_match"),
    ]


def test_category_label_store_derives_predictor_targets(tmp_path) -> None:
    store = CategoryLabelStore(tmp_path / "labels.jsonl")
    store.append(
        CategoryLabelRecord(
            product_id=10,
            candidate_category_ids=(1, 2, 3),
            selected_category_ids=(1, 3),
            labeled_at=datetime(2026, 5, 22, 1, 0, tzinfo=UTC),
        )
    )
    store.append(
        CategoryLabelRecord(
            product_id=11,
            candidate_category_ids=(4, 5, 6),
            selected_category_ids=(),
            labeled_at=datetime(2026, 5, 22, 1, 1, tzinfo=UTC),
        )
    )

    targets = store.predictor_targets()

    assert [(target.product_id, target.category_ids) for target in targets] == [
        (10, (1, 3)),
    ]


def test_category_label_store_uses_latest_label_for_duplicate_pairs(tmp_path) -> None:
    store = CategoryLabelStore(tmp_path / "labels.jsonl")
    store.append(
        CategoryLabelRecord(
            product_id=10,
            candidate_category_ids=(1, 2, 3),
            selected_category_ids=(2,),
            labeled_at=datetime(2026, 5, 22, 1, 0, tzinfo=UTC),
        )
    )
    store.append(
        CategoryLabelRecord(
            product_id=10,
            candidate_category_ids=(1, 2, 3),
            selected_category_ids=(3,),
            labeled_at=datetime(2026, 5, 22, 1, 1, tzinfo=UTC),
        )
    )

    labels = store.verifier_pair_labels()
    targets = store.predictor_targets()

    assert [(label.category_id, label.outcome) for label in labels] == [
        (1, "no_match"),
        (2, "no_match"),
        (3, "match"),
    ]
    assert [(target.product_id, target.category_ids) for target in targets] == [
        (10, (3,)),
    ]


def test_category_label_store_reports_labeled_and_unlabeled_pairs(tmp_path) -> None:
    store = CategoryLabelStore(tmp_path / "labels.jsonl")
    store.append(
        CategoryLabelRecord(
            product_id=10,
            candidate_category_ids=(1, 2, 3),
            selected_category_ids=(2,),
        )
    )

    assert store.has_pair_label(product_id=10, category_id=2)
    assert not store.has_pair_label(product_id=10, category_id=4)
    assert store.unlabeled_candidate_ids(
        product_id=10,
        candidate_category_ids=(2, 3, 4),
    ) == (4,)


def test_category_label_store_rejects_selected_categories_outside_candidates(tmp_path) -> None:
    store = CategoryLabelStore(tmp_path / "labels.jsonl")

    with pytest.raises(ValueError, match="selected_category_ids"):
        store.append(
            CategoryLabelRecord(
                product_id=10,
                candidate_category_ids=(1, 2, 3),
                selected_category_ids=(4,),
            )
        )
