import json

import joblib
import pytest
from stroyhub.ml.features import (
    CATEGORY_VERIFIER_FEATURE_SCHEMA_VERSION,
    CategoryVerifierCategoryInput,
    CategoryVerifierProductInput,
    build_category_verifier_features,
)
from stroyhub.ml.runtime import CategoryVerifier, CategoryVerifierModelUnavailableError
from stroyhub.ml.verifier import CategoryVerifierExample, train_category_verifier_baseline


def test_category_verifier_loads_current_model_and_uses_metadata_thresholds(tmp_path) -> None:
    model_dir = tmp_path / "models" / "v001"
    model_dir.mkdir(parents=True)
    current_path = tmp_path / "models" / "current"
    current_path.symlink_to("v001", target_is_directory=True)

    category = CategoryVerifierCategoryInput(id=10, slug="cement", name="Цемент")
    training_features = build_category_verifier_features(
        product=CategoryVerifierProductInput(
            source="test",
            title="Цемент М500",
        ),
        category=category,
    )
    model = train_category_verifier_baseline(
        model_version="v001",
        examples=[
            CategoryVerifierExample(
                product_id=1,
                category_id=10,
                outcome="match",
                features=training_features,
            )
        ],
    )
    joblib.dump(model, model_dir / "model.joblib")
    (model_dir / "metadata.json").write_text(
        json.dumps(
            {
                "model_version": "v001",
                "feature_schema_version": CATEGORY_VERIFIER_FEATURE_SCHEMA_VERSION,
                "thresholds": {"match": 0.60, "no_match": 0.40},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    verifier = CategoryVerifier.load(current_path)
    result = verifier.verify(
        product=CategoryVerifierProductInput(
            source="test",
            title="Цемент М500",
        ),
        category=category,
    )

    assert result.model_version == "v001"
    assert result.decision == "match"
    assert result.thresholds.match == 0.60
    assert result.thresholds.no_match == 0.40
    assert result.feature_schema_version == CATEGORY_VERIFIER_FEATURE_SCHEMA_VERSION


def test_category_verifier_reports_missing_model_explicitly(tmp_path) -> None:
    with pytest.raises(CategoryVerifierModelUnavailableError, match="model is unavailable"):
        CategoryVerifier.load(tmp_path / "models" / "current")
