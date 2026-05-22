from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import joblib
from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.ml.datasets import CategoryVerifierDatasetStatus, CategoryVerifierSnapshot
from stroyhub.ml.evaluation import (
    CategoryVerifierEvaluation,
    CategoryVerifierSplit,
    evaluate_category_verifier,
    split_category_verifier_examples,
)
from stroyhub.ml.features import (
    CATEGORY_VERIFIER_FEATURE_SCHEMA_VERSION,
    CategoryVerifierCategoryInput,
    CategoryVerifierProductInput,
    build_category_verifier_features,
)
from stroyhub.ml.labels import CategoryLabelStore
from stroyhub.ml.verifier import (
    MATCH_THRESHOLD,
    NO_MATCH_THRESHOLD,
    CategoryVerifierBaselineModel,
    CategoryVerifierExample,
    train_category_verifier_baseline,
)
from stroyhub.models import Category, SourceProduct


class InsufficientTrainingDataError(ValueError):
    def __init__(self, status: CategoryVerifierDatasetStatus) -> None:
        self.status = status
        super().__init__(
            "category verifier needs at least "
            f"{status.threshold} new labeled products; "
            f"got {status.new_labeled_product_count}"
        )


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierTrainingResult:
    model_version: str
    model_dir: Path
    model_path: Path
    metadata_path: Path
    error_report_path: Path
    snapshot: CategoryVerifierSnapshot
    split: CategoryVerifierSplit
    evaluation: CategoryVerifierEvaluation


def require_training_ready(
    *,
    status: CategoryVerifierDatasetStatus,
    force: bool,
) -> None:
    if force:
        return
    if not status.ready_for_training:
        raise InsufficientTrainingDataError(status)


def train_category_verifier_from_snapshot(
    *,
    session: Session,
    snapshot: CategoryVerifierSnapshot,
    models_dir: Path,
    reports_dir: Path,
    run_date: date,
) -> CategoryVerifierTrainingResult:
    examples = load_category_verifier_examples(session=session, snapshot=snapshot)
    split = split_category_verifier_examples(examples, run_date=run_date)
    return train_category_verifier_artifacts(
        model_version=snapshot.version,
        snapshot=snapshot,
        split=split,
        models_dir=models_dir,
        reports_dir=reports_dir,
        run_date=run_date,
    )


def train_category_verifier_artifacts(
    *,
    model_version: str,
    snapshot: CategoryVerifierSnapshot,
    split: CategoryVerifierSplit,
    models_dir: Path,
    reports_dir: Path,
    run_date: date,
) -> CategoryVerifierTrainingResult:
    model = train_category_verifier_baseline(
        model_version=model_version,
        examples=split.train_examples,
    )
    evaluation = evaluate_category_verifier(model=model, examples=split.eval_examples)

    model_dir = models_dir / model_version
    model_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    model_path = model_dir / "model.joblib"
    metadata_path = model_dir / "metadata.json"
    error_report_path = reports_dir / "errors" / f"{model_version}.jsonl"
    error_report_path.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump(model, model_path)
    metadata_path.write_text(
        json.dumps(
            _training_metadata(
                model=model,
                snapshot=snapshot,
                split=split,
                evaluation=evaluation,
                run_date=run_date,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_error_report(error_report_path, evaluation)
    _update_current_pointer(models_dir=models_dir, model_version=model_version)

    return CategoryVerifierTrainingResult(
        model_version=model_version,
        model_dir=model_dir,
        model_path=model_path,
        metadata_path=metadata_path,
        error_report_path=error_report_path,
        snapshot=snapshot,
        split=split,
        evaluation=evaluation,
    )


def load_category_verifier_examples(
    *,
    session: Session,
    snapshot: CategoryVerifierSnapshot,
) -> list[CategoryVerifierExample]:
    labels = CategoryLabelStore(snapshot.dataset_path).verifier_pair_labels()
    product_ids = {label.product_id for label in labels}
    category_ids = {label.category_id for label in labels}

    products = {
        product.id: product
        for product in session.scalars(
            select(SourceProduct).where(SourceProduct.id.in_(product_ids))
        )
    }
    categories = {
        category.id: category
        for category in session.scalars(select(Category).where(Category.id.in_(category_ids)))
    }
    all_categories = {category.id: category for category in session.scalars(select(Category))}

    missing_product_ids = product_ids - set(products)
    missing_category_ids = category_ids - set(categories)
    if missing_product_ids or missing_category_ids:
        raise ValueError(
            "snapshot references missing products/categories: "
            f"products={sorted(missing_product_ids)} "
            f"categories={sorted(missing_category_ids)}"
        )

    examples: list[CategoryVerifierExample] = []
    for label in labels:
        product = products[label.product_id]
        category = categories[label.category_id]
        examples.append(
            CategoryVerifierExample(
                product_id=label.product_id,
                category_id=label.category_id,
                outcome=label.outcome,
                features=build_category_verifier_features(
                    product=CategoryVerifierProductInput(
                        id=product.id,
                        source=product.source,
                        shop_id=product.shop_id,
                        title=product.title,
                        normalized_title=product.normalized_title,
                        category_raw=product.category_raw,
                        category_id=product.category_id,
                        description=product.description,
                    ),
                    category=_category_input(category),
                    category_path=_category_path(category, all_categories),
                ),
            )
        )
    return examples


def _training_metadata(
    *,
    model: CategoryVerifierBaselineModel,
    snapshot: CategoryVerifierSnapshot,
    split: CategoryVerifierSplit,
    evaluation: CategoryVerifierEvaluation,
    run_date: date,
) -> dict[str, object]:
    return {
        "model_version": model.model_version,
        "model_type": "token_baseline",
        "created_at": datetime.now(UTC).isoformat(),
        "run_date": run_date.isoformat(),
        "snapshot_version": snapshot.version,
        "snapshot_path": str(snapshot.dataset_path),
        "snapshot_metadata": {
            **asdict(snapshot.metadata),
            "created_at": snapshot.metadata.created_at.isoformat(),
        },
        "label_count": snapshot.metadata.label_count,
        "labeled_product_count": snapshot.metadata.labeled_product_count,
        "feature_schema_version": CATEGORY_VERIFIER_FEATURE_SCHEMA_VERSION,
        "thresholds": {
            "match": MATCH_THRESHOLD,
            "no_match": NO_MATCH_THRESHOLD,
        },
        "evaluation_split": asdict(split.metadata),
        "metrics": asdict(evaluation.metrics),
    }


def _write_error_report(path: Path, evaluation: CategoryVerifierEvaluation) -> None:
    with path.open("w", encoding="utf-8") as file:
        for error in evaluation.errors:
            file.write(json.dumps(asdict(error), ensure_ascii=False))
            file.write("\n")


def _update_current_pointer(*, models_dir: Path, model_version: str) -> None:
    current_path = models_dir / "current"
    if current_path.exists() or current_path.is_symlink():
        if current_path.is_dir() and not current_path.is_symlink():
            raise ValueError(f"{current_path} exists and is not a symlink")
        current_path.unlink()
    current_path.symlink_to(model_version, target_is_directory=True)


def _category_path(
    category: Category,
    categories_by_id: dict[int, Category],
) -> tuple[CategoryVerifierCategoryInput, ...]:
    path: list[CategoryVerifierCategoryInput] = []
    current: Category | None = category
    while current is not None:
        path.append(_category_input(current))
        current = categories_by_id.get(current.parent_id or 0)
    return tuple(reversed(path))


def _category_input(category: Category) -> CategoryVerifierCategoryInput:
    return CategoryVerifierCategoryInput(
        id=category.id,
        slug=category.slug,
        name=category.name,
        parent_id=category.parent_id,
    )
