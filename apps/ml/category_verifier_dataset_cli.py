from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from stroyhub.ml.datasets import CategoryVerifierDatasetStore


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manage category verifier dataset snapshots."
    )
    parser.add_argument("--labels-path", type=str)
    parser.add_argument("--datasets-dir", type=str)

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show live labels and latest snapshot counts.")
    subparsers.add_parser("snapshot", help="Create the next versioned dataset snapshot.")

    args = parser.parse_args(argv)
    store = _dataset_store(
        labels_path=args.labels_path,
        datasets_dir=args.datasets_dir,
    )

    if args.command == "status":
        status = store.status()
        print(f"live_labels={status.live_label_count}")
        print(f"live_labeled_products={status.live_labeled_product_count}")
        print(f"latest_snapshot={status.latest_snapshot_version or 'none'}")
        print(f"snapshot_labels={status.snapshot_label_count}")
        print(f"snapshot_labeled_products={status.snapshot_labeled_product_count}")
        print(f"new_labels={status.new_label_count}")
        print(f"new_labeled_products={status.new_labeled_product_count}")
        print(f"ready_for_training={str(status.ready_for_training).lower()}")
        print(f"threshold={status.threshold}")
        return 0

    if args.command == "snapshot":
        snapshot = store.create_next_snapshot()
        print(f"snapshot={snapshot.version}")
        print(f"dataset_path={snapshot.dataset_path}")
        print(f"metadata_path={snapshot.metadata_path}")
        print(f"label_count={snapshot.metadata.label_count}")
        print(f"labeled_product_count={snapshot.metadata.labeled_product_count}")
        return 0

    raise AssertionError(f"unsupported command: {args.command}")


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
