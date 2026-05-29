from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from stroyhub.ml.not_product_training import train_not_product_classifier_artifacts

DEFAULT_MODEL_DIR = Path(".var/ml/patron/models/v3")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the Patron model.")
    parser.add_argument("--dataset-path", type=str)
    parser.add_argument("--model-dir", type=str, default=str(DEFAULT_MODEL_DIR))
    parser.add_argument("--model-version", type=str)
    parser.add_argument("--run-date", type=date.fromisoformat)
    parser.add_argument("--train-ratio", type=float, default=0.80)
    parser.add_argument("--extra-dataset-path", action="append", default=[])
    parser.add_argument(
        "--model-type",
        choices=("linear", "naive_bayes"),
        default="linear",
    )
    args = parser.parse_args(argv)

    model_dir = Path(args.model_dir)
    dataset_path = (
        Path(args.dataset_path) if args.dataset_path else model_dir / "dataset.jsonl"
    )
    model_version = args.model_version or model_dir.name
    run_date = args.run_date or date.today()

    result = train_not_product_classifier_artifacts(
        dataset_path=dataset_path,
        model_dir=model_dir,
        model_version=model_version,
        run_date=run_date,
        train_ratio=args.train_ratio,
        model_type=args.model_type,
        extra_dataset_paths=[Path(path) for path in args.extra_dataset_path],
    )
    metrics = result.evaluation.metrics

    print(f"model_version={result.model_version}")
    print(f"dataset_path={result.dataset_path}")
    print(f"model_path={result.model_path}")
    print(f"metadata_path={result.metadata_path}")
    print(f"error_report_path={result.error_report_path}")
    print(f"train_labels={result.split.metadata.train_count}")
    print(f"eval_labels={result.split.metadata.eval_count}")
    print(f"eval_not_product={metrics.not_product_count}")
    print(f"eval_product={metrics.product_count}")
    print(f"accuracy={metrics.accuracy:.4f}")
    print(f"not_product_precision={metrics.not_product_precision:.4f}")
    print(f"not_product_recall={metrics.not_product_recall:.4f}")
    print(f"not_product_f1={metrics.not_product_f1:.4f}")
    print(f"errors={metrics.error_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
