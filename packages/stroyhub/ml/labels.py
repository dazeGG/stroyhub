from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

VerifierOutcome = Literal["match", "no_match"]


@dataclass(frozen=True, kw_only=True)
class CategoryLabelRecord:
    product_id: int
    candidate_category_ids: tuple[int, ...]
    selected_category_ids: tuple[int, ...]
    labeled_by: str | None = None
    labeled_at: datetime | None = None
    schema_version: int = 1


@dataclass(frozen=True, kw_only=True)
class VerifierPairLabel:
    product_id: int
    category_id: int
    outcome: VerifierOutcome
    labeled_by: str | None
    labeled_at: datetime


@dataclass(frozen=True, kw_only=True)
class PredictorTarget:
    product_id: int
    category_ids: tuple[int, ...]
    labeled_by: str | None
    labeled_at: datetime


class CategoryLabelStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def default(cls, *, root: Path | None = None) -> CategoryLabelStore:
        base_path = root or Path.cwd()
        return cls(base_path / ".var" / "ml" / "category_verifier" / "labels.jsonl")

    def append(self, record: CategoryLabelRecord) -> CategoryLabelRecord:
        normalized = _normalize_record(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(_record_to_json(normalized), ensure_ascii=False))
            file.write("\n")
        return normalized

    def read_records(self) -> list[CategoryLabelRecord]:
        if not self._path.exists():
            return []

        records: list[CategoryLabelRecord] = []
        with self._path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"invalid JSONL record at {self._path}:{line_number}"
                    ) from error
                records.append(_record_from_json(payload))
        return records

    def has_pair_label(self, *, product_id: int, category_id: int) -> bool:
        return (product_id, category_id) in self.labeled_pairs()

    def labeled_pairs(self) -> set[tuple[int, int]]:
        pairs: set[tuple[int, int]] = set()
        for record in self.read_records():
            for category_id in record.candidate_category_ids:
                pairs.add((record.product_id, category_id))
        return pairs

    def unlabeled_candidate_ids(
        self,
        *,
        product_id: int,
        candidate_category_ids: tuple[int, ...],
    ) -> tuple[int, ...]:
        labeled_pairs = self.labeled_pairs()
        return tuple(
            category_id
            for category_id in candidate_category_ids
            if (product_id, category_id) not in labeled_pairs
        )

    def verifier_pair_labels(self, *, latest_only: bool = True) -> list[VerifierPairLabel]:
        labels_by_pair: dict[tuple[int, int], VerifierPairLabel] = {}
        labels: list[VerifierPairLabel] = []
        for record in self.read_records():
            selected_ids = set(record.selected_category_ids)
            for category_id in record.candidate_category_ids:
                label = VerifierPairLabel(
                    product_id=record.product_id,
                    category_id=category_id,
                    outcome="match" if category_id in selected_ids else "no_match",
                    labeled_by=record.labeled_by,
                    labeled_at=_record_labeled_at(record),
                )
                if latest_only:
                    labels_by_pair[(record.product_id, category_id)] = label
                else:
                    labels.append(label)

        if latest_only:
            return list(labels_by_pair.values())
        return labels

    def predictor_targets(self, *, latest_only: bool = True) -> list[PredictorTarget]:
        targets_by_product: dict[int, PredictorTarget | None] = {}
        targets: list[PredictorTarget] = []
        for record in self.read_records():
            target = None
            if record.selected_category_ids:
                target = PredictorTarget(
                    product_id=record.product_id,
                    category_ids=record.selected_category_ids,
                    labeled_by=record.labeled_by,
                    labeled_at=_record_labeled_at(record),
                )

            if latest_only:
                targets_by_product[record.product_id] = target
            elif target is not None:
                targets.append(target)

        if latest_only:
            return [target for target in targets_by_product.values() if target is not None]
        return targets


def _normalize_record(record: CategoryLabelRecord) -> CategoryLabelRecord:
    if record.product_id <= 0:
        raise ValueError("product_id must be a positive integer")

    candidate_ids = _unique_ids(record.candidate_category_ids, field_name="candidate_category_ids")
    if not candidate_ids:
        raise ValueError("candidate_category_ids must not be empty")

    selected_ids = _unique_ids(record.selected_category_ids, field_name="selected_category_ids")
    unknown_selected_ids = set(selected_ids) - set(candidate_ids)
    if unknown_selected_ids:
        raise ValueError("selected_category_ids must be a subset of candidate_category_ids")

    labeled_at = record.labeled_at or datetime.now(UTC)
    if labeled_at.tzinfo is None:
        labeled_at = labeled_at.replace(tzinfo=UTC)

    return CategoryLabelRecord(
        product_id=record.product_id,
        candidate_category_ids=candidate_ids,
        selected_category_ids=selected_ids,
        labeled_by=record.labeled_by,
        labeled_at=labeled_at,
        schema_version=record.schema_version,
    )


def _unique_ids(values: tuple[int, ...], *, field_name: str) -> tuple[int, ...]:
    if not values:
        return ()

    seen: set[int] = set()
    unique_values: list[int] = []
    for value in values:
        if value <= 0:
            raise ValueError(f"{field_name} must contain positive integer ids")
        if value not in seen:
            unique_values.append(value)
            seen.add(value)
    return tuple(unique_values)


def _record_to_json(record: CategoryLabelRecord) -> dict[str, object]:
    return {
        "schema_version": record.schema_version,
        "product_id": record.product_id,
        "candidate_category_ids": list(record.candidate_category_ids),
        "selected_category_ids": list(record.selected_category_ids),
        "labeled_by": record.labeled_by,
        "labeled_at": _record_labeled_at(record).isoformat(),
    }


def _record_from_json(payload: object) -> CategoryLabelRecord:
    if not isinstance(payload, dict):
        raise ValueError("label record must be a JSON object")

    return _normalize_record(
        CategoryLabelRecord(
            schema_version=int(payload.get("schema_version", 1)),
            product_id=int(payload["product_id"]),
            candidate_category_ids=tuple(
                int(value) for value in payload["candidate_category_ids"]
            ),
            selected_category_ids=tuple(
                int(value) for value in payload["selected_category_ids"]
            ),
            labeled_by=_optional_str(payload.get("labeled_by")),
            labeled_at=_parse_datetime(str(payload["labeled_at"])),
        )
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _record_labeled_at(record: CategoryLabelRecord) -> datetime:
    return record.labeled_at or datetime.now(UTC)
