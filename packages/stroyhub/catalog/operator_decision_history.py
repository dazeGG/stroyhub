from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stroyhub.db.repositories import (
    JsonObject,
    OperatorDecisionCreate,
    OperatorDecisionRepository,
)
from stroyhub.models.tables import ProductMatch

_EVIDENCE_KEYS = (
    "engine",
    "status",
    "confidence",
    "method",
    "positive_evidence",
    "negative_evidence",
    "blockers",
)


def record_operator_decision(
    session: Session,
    *,
    decision_type: str,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    actor: str | None = None,
    reason: str | None = None,
    source_product_id: int | None = None,
    canonical_product_id: int | None = None,
    product_match_id: int | None = None,
    category_id: int | None = None,
    previous_state: JsonObject | None = None,
    new_state: JsonObject | None = None,
    decision_context: JsonObject | None = None,
    evidence: JsonObject | None = None,
    alternatives: JsonObject | None = None,
    metadata: JsonObject | None = None,
    decided_at: datetime | None = None,
) -> None:
    context_evidence, context_alternatives = _context_parts(decision_context)
    OperatorDecisionRepository(session).create(
        OperatorDecisionCreate(
            decision_type=decision_type,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            source_product_id=source_product_id,
            canonical_product_id=canonical_product_id,
            product_match_id=product_match_id,
            category_id=category_id,
            actor=actor,
            reason=reason,
            previous_state=previous_state,
            new_state=new_state,
            evidence=evidence or context_evidence,
            alternatives=alternatives or context_alternatives,
            metadata=metadata,
            decided_at=decided_at or datetime.now(UTC),
        )
    )


def match_state(match: ProductMatch | None) -> JsonObject | None:
    if match is None:
        return None

    return {
        "id": match.id,
        "canonical_product_id": match.canonical_product_id,
        "source_product_id": match.source_product_id,
        "status": match.status,
        "method": match.method,
        "confidence": _json_value(match.confidence),
        "reviewed_by": match.reviewed_by,
        "reviewed_at": match.reviewed_at.isoformat() if match.reviewed_at else None,
        "reason": match.reason,
    }


def decision_action(
    decision_context: JsonObject | None,
    *,
    default: str,
) -> str:
    if isinstance(decision_context, dict):
        raw_action = decision_context.get("action")
        if isinstance(raw_action, str) and raw_action.strip():
            return raw_action.strip()
    return default


def _context_parts(
    decision_context: JsonObject | None,
) -> tuple[JsonObject | None, JsonObject | None]:
    if not isinstance(decision_context, dict) or not decision_context:
        return None, None

    evidence = {
        key: decision_context[key]
        for key in _EVIDENCE_KEYS
        if key in decision_context
    }
    alternatives = decision_context.get("alternatives")
    if isinstance(alternatives, list):
        decision_context = {
            key: value
            for key, value in decision_context.items()
            if key != "alternatives"
        }

    if not evidence:
        evidence = {"decision": decision_context}
    else:
        evidence["decision"] = decision_context

    if isinstance(alternatives, list):
        return evidence, {"items": alternatives}
    return evidence, None


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value
