from datetime import UTC, datetime

from stroyhub.models import Shop


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

