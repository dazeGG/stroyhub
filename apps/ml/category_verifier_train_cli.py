from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from stroyhub.db import SessionLocal
from stroyhub.ml.datasets import CategoryVerifierDatasetStore
from stroyhub.ml.training import (
    InsufficientTrainingDataError,
    require_training_ready,
    train_category_verifier_from_snapshot,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the category verifier model.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--labels-path", type=str)
    parser.add_argument("--datasets-dir", type=str)
    parser.add_argument("--models-dir", type=str)
    parser.add_argument("--reports-dir", type=str)
    parser.add_argument("--run-date", type=date.fromisoformat)
    args = parser.parse_args(argv)

    dataset_store = _dataset_store(
        labels_path=args.labels_path,
        datasets_dir=args.datasets_dir,
    )
    status = dataset_store.status()
    try:
        require_training_ready(status=status, force=args.force)
    except InsufficientTrainingDataError as error:
        print(error)
        print(f"new_labeled_products={status.new_labeled_product_count}")
        print(f"threshold={status.threshold}")
        print("Pass --force to train anyway.")
        return 1

    snapshot = dataset_store.create_next_snapshot()
    artifact_root = snapshot.dataset_path.parent.parent
    models_dir = Path(args.models_dir) if args.models_dir else artifact_root / "models"
    reports_dir = (
        Path(args.reports_dir) if args.reports_dir else artifact_root / "reports"
    )
    run_date = args.run_date or date.today()

    with SessionLocal() as session:
        result = train_category_verifier_from_snapshot(
            session=session,
            snapshot=snapshot,
            models_dir=models_dir,
            reports_dir=reports_dir,
            run_date=run_date,
        )

    print(f"model_version={result.model_version}")
    print(f"snapshot={result.snapshot.version}")
    print(f"model_path={result.model_path}")
    print(f"metadata_path={result.metadata_path}")
    print(f"error_report_path={result.error_report_path}")
    print(f"train_labels={result.split.metadata.train_label_count}")
    print(f"eval_labels={result.split.metadata.eval_label_count}")
    print(f"accuracy={result.evaluation.metrics.accuracy:.4f}")
    print(f"f1={result.evaluation.metrics.f1:.4f}")
    return 0


def _dataset_store(
    *,
    labels_path: str | None,
    datasets_dir: str | None,
) -> CategoryVerifierDatasetStore:
    if labels_path is None and datasets_dir is None:
        return CategoryVerifierDatasetStore.default()
    if labels_path is None or datasets_dir is None:
        raise SystemExit("--labels-path and --datasets-dir must be passed together")
    return CategoryVerifierDatasetStore.from_paths(
        labels_path=Path(labels_path),
        datasets_dir=Path(datasets_dir),
    )


if __name__ == "__main__":
    raise SystemExit(main())
