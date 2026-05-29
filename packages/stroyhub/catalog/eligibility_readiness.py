from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from stroyhub.models import SourceProduct


def count_missing_catalog_eligibility(
    session: Session,
    *,
    include_inactive: bool = False,
) -> int:
    eligibility_type = func.jsonb_typeof(SourceProduct.raw["catalog_eligibility"])
    statement = select(func.count(SourceProduct.id)).where(
        or_(eligibility_type.is_(None), eligibility_type != "object")
    )
    if not include_inactive:
        statement = statement.where(SourceProduct.is_active.is_(True))
    return int(session.scalar(statement) or 0)
