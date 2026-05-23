from dataclasses import dataclass
from datetime import UTC, datetime

from stroyhub.models import Shop


@dataclass(frozen=True, kw_only=True)
class EnqueueFailure:
    operation: str
    failed_at: str
    reason: str


def mark_enqueue_failed(
    shop: Shop,
    *,
    operation: str,
    reason: str,
) -> None:
    raw = dict(shop.raw or {})
    raw["enqueue_failed"] = {
        "operation": operation,
        "failed_at": datetime.now(UTC).isoformat(),
        "reason": reason,
    }
    shop.raw = raw


def clear_enqueue_failed(shop: Shop) -> None:
    raw = dict(shop.raw or {})
    if "enqueue_failed" not in raw:
        return

    raw.pop("enqueue_failed", None)
    shop.raw = raw or None


def enqueue_failure_state(raw: object) -> EnqueueFailure | None:
    if not isinstance(raw, dict):
        return None

    value = raw.get("enqueue_failed")
    if not isinstance(value, dict):
        return None

    operation = value.get("operation")
    failed_at = value.get("failed_at")
    reason = value.get("reason")
    if (
        not isinstance(operation, str)
        or not isinstance(failed_at, str)
        or not isinstance(reason, str)
    ):
        return None

    return EnqueueFailure(operation=operation, failed_at=failed_at, reason=reason)
