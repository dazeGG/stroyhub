from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from stroyhub.ml.labels import CategoryLabelRecord, CategoryLabelStore

TRAINING_READY_NEW_PRODUCT_THRESHOLD = 50
SNAPSHOT_SCHEMA_VERSION = 1

_SNAPSHOT_PATTERN = re.compile(r"^v(?P<number>\d{3,})\.jsonl$")


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierSnapshotMetadata:
    version: str
    created_at: datetime
    source_label_file: str
    schema_version: int
    label_count: int
    labeled_product_count: int


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierSnapshot:
    version: str
    dataset_path: Path
    metadata_path: Path
    metadata: CategoryVerifierSnapshotMetadata


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierDatasetStatus:
    live_label_count: int
    live_labeled_product_count: int
    latest_snapshot_version: str | None
    snapshot_label_count: int
    snapshot_labeled_product_count: int
    new_label_count: int
    new_labeled_product_count: int
    ready_for_training: bool
    threshold: int = TRAINING_READY_NEW_PRODUCT_THRESHOLD


class CategoryVerifierDatasetStore:
    def __init__(self, *, label_store: CategoryLabelStore, datasets_dir: Path) -> None:
        self._label_store = label_store
        self._datasets_dir = datasets_dir

    @property
    def datasets_dir(self) -> Path:
        return self._datasets_dir

    @classmethod
    def default(cls, *, root: Path | None = None) -> CategoryVerifierDatasetStore:
        label_store = CategoryLabelStore.default(root=root)
        return cls(label_store=label_store, datasets_dir=label_store.path.parent / "datasets")

    @classmethod
    def from_paths(
        cls,
        *,
        labels_path: str | Path,
        datasets_dir: str | Path,
    ) -> CategoryVerifierDatasetStore:
        return cls(
            label_store=CategoryLabelStore.from_path(labels_path),
            datasets_dir=Path(datasets_dir),
        )

    def latest_snapshot(self) -> CategoryVerifierSnapshot | None:
        version = self.latest_snapshot_version()
        if version is None:
            return None
        return self.snapshot(version)

    def latest_snapshot_version(self) -> str | None:
        versions = [
            version
            for path in self._datasets_dir.glob("v*.jsonl")
            if (version := _parse_snapshot_version(path.name)) is not None
        ]
        if not versions:
            return None
        return max(versions, key=_version_number)

    def next_snapshot_version(self) -> str:
        latest_version = self.latest_snapshot_version()
        if latest_version is None:
            return "v001"
        return f"v{_version_number(latest_version) + 1:03d}"

    def snapshot(self, version: str) -> CategoryVerifierSnapshot:
        dataset_path = self._dataset_path(version)
        metadata_path = self._metadata_path(version)
        if not dataset_path.exists():
            raise FileNotFoundError(dataset_path)

        if metadata_path.exists():
            metadata = _metadata_from_json(json.loads(metadata_path.read_text("utf-8")))
        else:
            metadata = _metadata_from_records(
                version=version,
                records=CategoryLabelStore(dataset_path).read_records(),
                source_label_file=str(self._label_store.path),
                created_at=datetime.fromtimestamp(dataset_path.stat().st_mtime, tz=UTC),
            )

        return CategoryVerifierSnapshot(
            version=version,
            dataset_path=dataset_path,
            metadata_path=metadata_path,
            metadata=metadata,
        )

    def create_next_snapshot(
        self,
        *,
        created_at: datetime | None = None,
    ) -> CategoryVerifierSnapshot:
        version = self.next_snapshot_version()
        self._datasets_dir.mkdir(parents=True, exist_ok=True)

        dataset_path = self._dataset_path(version)
        metadata_path = self._metadata_path(version)
        if dataset_path.exists() or metadata_path.exists():
            raise FileExistsError(f"snapshot {version} already exists")

        source_path = self._label_store.path
        if source_path.exists():
            shutil.copyfile(source_path, dataset_path)
        else:
            dataset_path.write_text("", encoding="utf-8")

        snapshot_records = CategoryLabelStore(dataset_path).read_records()
        metadata = _metadata_from_records(
            version=version,
            records=snapshot_records,
            source_label_file=str(source_path),
            created_at=created_at or datetime.now(UTC),
        )
        metadata_path.write_text(
            json.dumps(_metadata_to_json(metadata), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        return CategoryVerifierSnapshot(
            version=version,
            dataset_path=dataset_path,
            metadata_path=metadata_path,
            metadata=metadata,
        )

    def status(self) -> CategoryVerifierDatasetStatus:
        live_records = self._label_store.read_records()
        latest_snapshot = self.latest_snapshot()
        snapshot_label_count = 0
        snapshot_labeled_product_count = 0
        latest_snapshot_version = None

        if latest_snapshot is not None:
            latest_snapshot_version = latest_snapshot.version
            snapshot_label_count = latest_snapshot.metadata.label_count
            snapshot_labeled_product_count = latest_snapshot.metadata.labeled_product_count

        live_label_count = len(live_records)
        live_labeled_product_count = _labeled_product_count(live_records)
        new_labeled_product_count = max(
            live_labeled_product_count - snapshot_labeled_product_count,
            0,
        )

        return CategoryVerifierDatasetStatus(
            live_label_count=live_label_count,
            live_labeled_product_count=live_labeled_product_count,
            latest_snapshot_version=latest_snapshot_version,
            snapshot_label_count=snapshot_label_count,
            snapshot_labeled_product_count=snapshot_labeled_product_count,
            new_label_count=max(live_label_count - snapshot_label_count, 0),
            new_labeled_product_count=new_labeled_product_count,
            ready_for_training=new_labeled_product_count
            >= TRAINING_READY_NEW_PRODUCT_THRESHOLD,
        )

    def _dataset_path(self, version: str) -> Path:
        _validate_version(version)
        return self._datasets_dir / f"{version}.jsonl"

    def _metadata_path(self, version: str) -> Path:
        _validate_version(version)
        return self._datasets_dir / f"{version}.meta.json"


def _metadata_from_records(
    *,
    version: str,
    records: list[CategoryLabelRecord],
    source_label_file: str,
    created_at: datetime,
) -> CategoryVerifierSnapshotMetadata:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    return CategoryVerifierSnapshotMetadata(
        version=version,
        created_at=created_at,
        source_label_file=source_label_file,
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        label_count=len(records),
        labeled_product_count=_labeled_product_count(records),
    )


def _labeled_product_count(records: list[CategoryLabelRecord]) -> int:
    return len({record.product_id for record in records})


def _metadata_to_json(metadata: CategoryVerifierSnapshotMetadata) -> dict[str, object]:
    payload = asdict(metadata)
    payload["created_at"] = metadata.created_at.isoformat()
    return payload


def _metadata_from_json(payload: object) -> CategoryVerifierSnapshotMetadata:
    if not isinstance(payload, dict):
        raise ValueError("snapshot metadata must be a JSON object")

    return CategoryVerifierSnapshotMetadata(
        version=str(payload["version"]),
        created_at=_parse_datetime(str(payload["created_at"])),
        source_label_file=str(payload["source_label_file"]),
        schema_version=int(payload["schema_version"]),
        label_count=int(payload["label_count"]),
        labeled_product_count=int(payload["labeled_product_count"]),
    )


def _parse_snapshot_version(file_name: str) -> str | None:
    match = _SNAPSHOT_PATTERN.match(file_name)
    if match is None:
        return None
    return f"v{int(match.group('number')):03d}"


def _version_number(version: str) -> int:
    _validate_version(version)
    return int(version.removeprefix("v"))


def _validate_version(version: str) -> None:
    if _SNAPSHOT_PATTERN.match(f"{version}.jsonl") is None:
        raise ValueError("snapshot version must look like v001")


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
