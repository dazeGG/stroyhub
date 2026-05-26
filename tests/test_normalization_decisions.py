from dataclasses import dataclass
from decimal import Decimal

from stroyhub.catalog.normalization_decisions import (
    decide_normalization,
    decide_normalization_batch,
)
from stroyhub.parsers.common import JsonObject, normalize_title


@dataclass(frozen=True, kw_only=True)
class SourceOffer:
    id: int
    title: str
    category_id: int | None = 1
    source: str = "2gis"
    shop_id: int = 10
    category_raw: str | None = "Сухие смеси"
    unit_raw: str | None = None
    raw: JsonObject | None = None
    is_not_product: bool = False

    @property
    def normalized_title(self) -> str:
        return normalize_title(self.title)


@dataclass(frozen=True, kw_only=True)
class CanonicalOffer:
    id: int
    title: str
    category_id: int | None = 1
    unit_raw: str | None = None
    attributes: JsonObject | None = None

    @property
    def normalized_title(self) -> str:
        return normalize_title(self.title)


def test_decision_engine_auto_attaches_single_safe_candidate_with_evidence() -> None:
    source = _source(title="Цемент М500 50кг")
    canonical = _canonical(title=" цемент   м500 50кг ")

    decision = decide_normalization(source, candidates=(canonical,))

    assert decision.status == "ready_to_accept"
    assert decision.action == "attach_to_existing"
    assert decision.canonical_product_id == canonical.id
    assert decision.confidence == Decimal("1.000")
    reason = decision.as_reason()
    assert reason["positive_evidence"]
    assert reason["negative_evidence"]
    assert reason["alternatives"][0]["blockers"] == []


def test_decision_engine_creates_new_product_when_no_candidates_are_reviewable() -> None:
    source = _source(id=2, title="OSB-3 1,25х2,5м 9мм")

    decision = decide_normalization(source, candidates=())
    batch_decision = decide_normalization_batch(
        (source,),
        candidates_by_source_product_id={},
    )[0]

    assert decision.status == "ready_to_accept"
    assert decision.action == "create_normalized_product"
    assert decision.positive_evidence
    assert decision.negative_evidence
    assert batch_decision.as_reason() == decision.as_reason()


def test_decision_engine_sends_conflicting_attributes_to_review() -> None:
    source = _source(id=3, title="Цемент М500 25кг")
    canonical = _canonical(id=30, title="Цемент М500 50кг")

    decision = decide_normalization(source, candidates=(canonical,))

    assert decision.status == "needs_review"
    assert decision.action == "needs_review"
    assert "weight_conflict" in decision.blockers
    assert any(
        evidence.kind == "attribute_conflict" and evidence.result == "fail"
        for evidence in decision.negative_evidence
    )


def test_decision_engine_sends_duplicate_candidates_to_review() -> None:
    source = _source(id=4, title="Клей плиточный KNAUF Флизен 25кг")
    first = _canonical(id=40, title="Клей плиточный KNAUF Флизен 25кг")
    second = _canonical(id=41, title="Клей плиточный KNAUF Флизен 25кг")

    decision = decide_normalization(source, candidates=(first, second))

    assert decision.status == "needs_review"
    assert decision.action == "needs_review"
    assert "ambiguous_candidates" in decision.blockers
    assert len(decision.alternatives) == 2


def test_decision_engine_quarantines_ineligible_source_offers() -> None:
    source = _source(
        id=5,
        title="Гвозди",
        raw={"catalog_eligibility": {"status": "ineligible"}},
        is_not_product=True,
    )

    decision = decide_normalization(source, candidates=())

    assert decision.status == "data_problem"
    assert decision.action == "quarantine"
    assert decision.confidence == Decimal("0.000")
    assert decision.negative_evidence


def test_decision_engine_respects_operator_rejected_candidates() -> None:
    source = _source(id=6, title="Цемент М500 50кг")
    canonical = _canonical(id=60, title="Цемент М500 50кг")

    decision = decide_normalization(
        source,
        candidates=(canonical,),
        rejected_canonical_product_ids=(canonical.id,),
    )

    assert decision.status == "needs_review"
    assert "operator_rejected" in decision.blockers


def _source(
    *,
    id: int = 1,
    title: str,
    category_id: int | None = 1,
    raw: JsonObject | None = None,
    is_not_product: bool = False,
) -> SourceOffer:
    return SourceOffer(
        id=id,
        title=title,
        category_id=category_id,
        raw=raw or {"catalog_eligibility": {"status": "eligible"}},
        is_not_product=is_not_product,
    )


def _canonical(
    *,
    id: int = 10,
    title: str,
    category_id: int | None = 1,
) -> CanonicalOffer:
    return CanonicalOffer(id=id, title=title, category_id=category_id)
