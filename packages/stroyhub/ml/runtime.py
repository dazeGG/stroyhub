from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib

from stroyhub.ml.features import (
    CategoryVerifierCategoryInput,
    CategoryVerifierFeatureRow,
    CategoryVerifierProductInput,
    build_category_verifier_features,
)
from stroyhub.ml.verifier import CategoryVerifierBaselineModel, VerifierDecision


class CategoryVerifierModelUnavailableError(FileNotFoundError):
    pass


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierThresholds:
    match: float
    no_match: float


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierResult:
    decision: VerifierDecision
    confidence: float
    model_version: str
    thresholds: CategoryVerifierThresholds
    feature_schema_version: str


class CategoryVerifier:
    def __init__(
        self,
        *,
        model: CategoryVerifierBaselineModel,
        metadata: dict[str, Any],
    ) -> None:
        self._model = model
        self._metadata = metadata
        self._thresholds = _thresholds_from_metadata(metadata)

    @property
    def model_version(self) -> str:
        return str(self._metadata.get("model_version") or self._model.model_version)

    @classmethod
    def default(cls, *, root: Path | None = None) -> CategoryVerifier:
        base_path = root or Path.cwd()
        return cls.load(base_path / ".var" / "ml" / "category_verifier" / "models" / "current")

    @classmethod
    def load(cls, model_dir: str | Path) -> CategoryVerifier:
        model_dir = Path(model_dir)
        model_path = model_dir / "model.joblib"
        metadata_path = model_dir / "metadata.json"
        if not model_path.exists() or not metadata_path.exists():
            raise CategoryVerifierModelUnavailableError(
                f"category verifier model is unavailable at {model_dir}"
            )

        model = joblib.load(model_path)
        if not isinstance(model, CategoryVerifierBaselineModel):
            raise TypeError(f"unsupported category verifier model artifact: {type(model)!r}")

        metadata = json.loads(metadata_path.read_text("utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("category verifier metadata must be a JSON object")

        return cls(model=model, metadata=metadata)

    def verify(
        self,
        *,
        product: CategoryVerifierProductInput,
        category: CategoryVerifierCategoryInput,
        category_path: tuple[CategoryVerifierCategoryInput, ...] = (),
    ) -> CategoryVerifierResult:
        features = build_category_verifier_features(
            product=product,
            category=category,
            category_path=category_path,
        )
        return self.verify_features(features)

    def verify_features(self, features: CategoryVerifierFeatureRow) -> CategoryVerifierResult:
        confidence = self._model.confidence(features)
        if confidence >= self._thresholds.match:
            decision: VerifierDecision = "match"
        elif confidence <= self._thresholds.no_match:
            decision = "no_match"
        else:
            decision = "uncertain"

        return CategoryVerifierResult(
            decision=decision,
            confidence=confidence,
            model_version=self.model_version,
            thresholds=self._thresholds,
            feature_schema_version=features.schema_version,
        )


def _thresholds_from_metadata(metadata: dict[str, Any]) -> CategoryVerifierThresholds:
    thresholds = metadata.get("thresholds")
    if isinstance(thresholds, dict):
        return CategoryVerifierThresholds(
            match=float(thresholds["match"]),
            no_match=float(thresholds["no_match"]),
        )
    return CategoryVerifierThresholds(
        match=float(metadata["match_threshold"]),
        no_match=float(metadata["no_match_threshold"]),
    )
