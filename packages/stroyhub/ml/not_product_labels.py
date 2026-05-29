from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

NotProductLabel = Literal["product", "not_product"]


@dataclass(frozen=True, kw_only=True)
class NotProductLabelRecord:
    source_product_id: int
    label: NotProductLabel
    labeled_by: str | None = None
    labeled_at: datetime | None = None
    schema_version: int = 1


class NotProductLabelStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def default(cls, *, root: Path | None = None) -> NotProductLabelStore:
        base_path = root or Path.cwd()
        return cls(base_path / ".var" / "ml" / "patron" / "human_labels.jsonl")

    @classmethod
    def from_path(cls, path: str | Path) -> NotProductLabelStore:
        return cls(Path(path))

    def append(self, record: NotProductLabelRecord) -> NotProductLabelRecord:
        normalized = _normalize_record(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(_record_to_json(normalized), ensure_ascii=False))
            file.write("\n")
        return normalized

    def pop_last(self) -> None:
        if not self._path.exists():
            return
        lines = [line for line in self._path.read_text(encoding="utf-8").splitlines() if line]
        if not lines:
            return
        lines.pop()
        self._path.write_text(
            "\n".join(lines) + ("\n" if lines else ""),
            encoding="utf-8",
        )

    def read_records(self) -> list[NotProductLabelRecord]:
        if not self._path.exists():
            return []

        records: list[NotProductLabelRecord] = []
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

    def latest_labels(self) -> dict[int, NotProductLabelRecord]:
        labels: dict[int, NotProductLabelRecord] = {}
        for record in self.read_records():
            labels[record.source_product_id] = record
        return labels

    def labeled_product_ids(self) -> set[int]:
        return set(self.latest_labels())


def _normalize_record(record: NotProductLabelRecord) -> NotProductLabelRecord:
    if record.source_product_id <= 0:
        raise ValueError("source_product_id must be a positive integer")
    if record.label not in {"product", "not_product"}:
        raise ValueError("label must be product or not_product")

    labeled_at = record.labeled_at or datetime.now(UTC)
    if labeled_at.tzinfo is None:
        labeled_at = labeled_at.replace(tzinfo=UTC)

    return NotProductLabelRecord(
        schema_version=record.schema_version,
        source_product_id=record.source_product_id,
        label=record.label,
        labeled_by=record.labeled_by,
        labeled_at=labeled_at,
    )


def _record_to_json(record: NotProductLabelRecord) -> dict[str, object]:
    return {
        "schema_version": record.schema_version,
        "source_product_id": record.source_product_id,
        "label": record.label,
        "labeled_by": record.labeled_by,
        "labeled_at": _record_labeled_at(record).isoformat(),
    }


def _record_from_json(payload: object) -> NotProductLabelRecord:
    if not isinstance(payload, dict):
        raise ValueError("not-product label record must be a JSON object")

    return _normalize_record(
        NotProductLabelRecord(
            schema_version=int(payload.get("schema_version", 1)),
            source_product_id=int(payload["source_product_id"]),
            label=_label(payload["label"]),
            labeled_by=_optional_str(payload.get("labeled_by")),
            labeled_at=_parse_datetime(str(payload["labeled_at"])),
        )
    )


def _label(value: object) -> NotProductLabel:
    if value == "product":
        return "product"
    if value == "not_product":
        return "not_product"
    raise ValueError("label must be product or not_product")


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _record_labeled_at(record: NotProductLabelRecord) -> datetime:
    return record.labeled_at or datetime.now(UTC)
