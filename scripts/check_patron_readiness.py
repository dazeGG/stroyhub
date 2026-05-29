from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from stroyhub.catalog.eligibility_readiness import count_missing_catalog_eligibility
from stroyhub.db import SessionLocal
from stroyhub.ml.not_product_classifier import (
    NotProductClassifierModelUnavailableError,
    PatronClassifier,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check Patron runtime artifacts and catalog eligibility backfill readiness."
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        help="Patron model directory. Defaults to STROYHUB_PATRON_MODEL_DIR.",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Only verify that the Patron model artifact can be loaded.",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive source products in the catalog eligibility check.",
    )
    args = parser.parse_args(argv)

    model_dir = PatronClassifier.default_model_dir(model_dir=args.model_dir)
    try:
        classifier = PatronClassifier.load(model_dir)
    except NotProductClassifierModelUnavailableError as error:
        print("patron_ready=false")
        print("model_loaded=false")
        print(f"patron_model_dir={model_dir}")
        print(f"error={error}")
        return 1

    print("model_loaded=true")
    print(f"model_name={classifier.model_name}")
    print(f"model_version={classifier.model_version}")
    print(f"patron_model_dir={model_dir}")

    if args.skip_db:
        print("patron_ready=true")
        return 0

    try:
        with SessionLocal() as session:
            missing_count = count_missing_catalog_eligibility(
                session,
                include_inactive=args.include_inactive,
            )
    except SQLAlchemyError as error:
        print("patron_ready=false")
        print(f"error={error}")
        return 3

    print(f"missing_catalog_eligibility={missing_count}")
    if missing_count:
        print("patron_ready=false")
        return 2

    print("patron_ready=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
