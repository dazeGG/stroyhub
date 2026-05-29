from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from stroyhub.db import SessionLocal
from stroyhub.ml.patron_dataset import build_patron_dataset_snapshot

DEFAULT_MODEL_DIR = Path(".var/ml/patron/models/v3")
DEFAULT_BULK_LABELS_PATH = Path(".var/ml/patron/labels.jsonl")
DEFAULT_HUMAN_LABELS_PATH = Path(".var/ml/patron/human_labels.jsonl")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a Patron dataset snapshot.")
    parser.add_argument("--model-dir", type=str, default=str(DEFAULT_MODEL_DIR))
    parser.add_argument("--dataset-path", type=str)
    parser.add_argument("--manifest-path", type=str)
    parser.add_argument("--model-version", type=str)
    parser.add_argument("--bulk-labels-path", type=str, default=str(DEFAULT_BULK_LABELS_PATH))
    parser.add_argument("--human-labels-path", type=str, default=str(DEFAULT_HUMAN_LABELS_PATH))
    parser.add_argument("--include-inactive", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--created-at", type=datetime.fromisoformat)
    args = parser.parse_args(argv)

    model_dir = Path(args.model_dir)
    dataset_path = Path(args.dataset_path) if args.dataset_path else model_dir / "dataset.jsonl"
    manifest_path = (
        Path(args.manifest_path)
        if args.manifest_path
        else model_dir / "dataset_manifest.json"
    )
    model_version = args.model_version or model_dir.name

    with SessionLocal() as session:
        result = build_patron_dataset_snapshot(
            session=session,
            dataset_path=dataset_path,
            manifest_path=manifest_path,
            model_version=model_version,
            bulk_labels_path=Path(args.bulk_labels_path),
            human_labels_path=Path(args.human_labels_path),
            include_inactive=args.include_inactive,
            limit=args.limit,
            created_at=args.created_at,
        )

    print(f"model_version={model_version}")
    print(f"dataset_path={result.dataset_path}")
    print(f"manifest_path={result.manifest_path}")
    print(f"record_count={result.record_count}")
    print(f"label_counts={result.label_counts}")
    print(f"label_source_counts={result.label_source_counts}")
    print(f"label_priority_counts={result.label_priority_counts}")
    print(f"review_label_count={result.review_label_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
