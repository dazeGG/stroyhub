from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from stroyhub.catalog.attributes import ExtractedAttribute, extract_product_attributes
from stroyhub.catalog.tokenization import tokenize_normalized_text
from stroyhub.parsers.common import JsonObject, normalize_title

NormalizationDecisionAction = Literal[
    "create_normalized_product",
    "attach_to_existing",
    "needs_review",
    "quarantine",
]
NormalizationDecisionStatus = Literal["ready_to_accept", "needs_review", "data_problem"]
NormalizationEvidenceResult = Literal["pass", "warn", "fail"]

_ENGINE_VERSION = "normalization_decision_v1"
_READY_CONFIDENCE = Decimal("0.970")
_REVIEW_CONFIDENCE = Decimal("0.750")
_PROTECTED_ATTRIBUTE_KINDS = frozenset(
    {
        "brand",
        "dimension",
        "grade",
        "material",
        "model",
        "package_count",
        "product_type",
        "selling_unit",
        "thickness",
        "volume",
        "weight",
    }
)
_SPECIFIC_ATTRIBUTE_KINDS = frozenset(
    {
        "area",
        "dimension",
        "grade",
        "length",
        "package_count",
        "thickness",
        "volume",
        "weight",
    }
)
_LOW_VALUE_TOKENS = frozenset(
    {
        "в",
        "для",
        "до",
        "и",
        "из",
        "на",
        "от",
        "по",
        "под",
        "с",
        "со",
        "материал",
        "материалы",
        "строительный",
        "универсальная",
        "универсальное",
        "универсальный",
    }
)


class NormalizationSourceProductLike(Protocol):
    id: int
    source: str
    shop_id: int
    title: str
    normalized_title: str
    category_id: int | None
    category_raw: str | None
    unit_raw: str | None
    raw: JsonObject | None
    is_not_product: bool


class NormalizationCanonicalProductLike(Protocol):
    id: int
    title: str
    normalized_title: str
    category_id: int | None
    unit_raw: str | None
    attributes: JsonObject | None


@dataclass(frozen=True, kw_only=True)
class NormalizationEvidence:
    kind: str
    result: NormalizationEvidenceResult
    message: str
    source_value: str | None = None
    target_value: str | None = None

    def as_raw(self) -> JsonObject:
        raw: JsonObject = {
            "kind": self.kind,
            "result": self.result,
            "message": self.message,
        }
        if self.source_value is not None:
            raw["source_value"] = self.source_value
        if self.target_value is not None:
            raw["target_value"] = self.target_value
        return raw


@dataclass(frozen=True, kw_only=True)
class NormalizationAlternative:
    canonical_product_id: int
    canonical_title: str
    confidence: Decimal
    method: str
    positive_evidence: tuple[NormalizationEvidence, ...]
    negative_evidence: tuple[NormalizationEvidence, ...]
    blockers: tuple[str, ...]

    @property
    def is_ready(self) -> bool:
        return not self.blockers and self.confidence >= _READY_CONFIDENCE

    @property
    def is_reviewable(self) -> bool:
        return self.confidence >= _REVIEW_CONFIDENCE or bool(self.blockers)

    def as_raw(self) -> JsonObject:
        return {
            "canonical_product_id": self.canonical_product_id,
            "canonical_title": self.canonical_title,
            "confidence": str(self.confidence),
            "method": self.method,
            "positive_evidence": [
                evidence.as_raw() for evidence in self.positive_evidence
            ],
            "negative_evidence": [
                evidence.as_raw() for evidence in self.negative_evidence
            ],
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, kw_only=True)
class NormalizationDecision:
    source_product_id: int
    action: NormalizationDecisionAction
    status: NormalizationDecisionStatus
    confidence: Decimal
    positive_evidence: tuple[NormalizationEvidence, ...]
    negative_evidence: tuple[NormalizationEvidence, ...]
    canonical_product_id: int | None = None
    canonical_title: str | None = None
    method: str = "attribute_rules"
    alternatives: tuple[NormalizationAlternative, ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def is_auto_accept(self) -> bool:
        return self.status == "ready_to_accept" and self.action in {
            "attach_to_existing",
            "create_normalized_product",
        }

    def as_reason(self) -> JsonObject:
        raw: JsonObject = {
            "engine": _ENGINE_VERSION,
            "action": self.action,
            "status": self.status,
            "confidence": str(self.confidence),
            "method": self.method,
            "positive_evidence": [
                evidence.as_raw() for evidence in self.positive_evidence
            ],
            "negative_evidence": [
                evidence.as_raw() for evidence in self.negative_evidence
            ],
            "blockers": list(self.blockers),
            "alternatives": [alternative.as_raw() for alternative in self.alternatives],
        }
        if self.canonical_product_id is not None:
            raw["canonical_product_id"] = self.canonical_product_id
        if self.canonical_title is not None:
            raw["canonical_title"] = self.canonical_title
        return raw


@dataclass(frozen=True, kw_only=True)
class _PreparedProduct:
    id: int
    title: str
    normalized_title: str
    category_id: int | None
    category_raw: str | None
    unit_raw: str | None
    tokens: frozenset[str]
    attributes: tuple[ExtractedAttribute, ...]
    extraction_reasons: tuple[str, ...]
    extraction_confidence: Decimal


class NormalizationDecisionEngine:
    def decide(
        self,
        source_product: NormalizationSourceProductLike,
        *,
        candidates: Iterable[NormalizationCanonicalProductLike] = (),
        rejected_canonical_product_ids: Iterable[int] = (),
    ) -> NormalizationDecision:
        source = _prepare_source(source_product)
        positive_evidence = list(_source_positive_evidence(source, source_product))
        negative_evidence = list(_source_negative_evidence(source, source_product))

        if source_product.is_not_product:
            negative_evidence.append(
                NormalizationEvidence(
                    kind="source_product_flag",
                    result="fail",
                    message="Source product is marked as not a product.",
                )
            )
            return _decision(
                source_product_id=source.id,
                action="quarantine",
                status="data_problem",
                confidence=Decimal("0.000"),
                positive_evidence=positive_evidence,
                negative_evidence=negative_evidence,
                blockers=("source_product_flag",),
            )

        eligibility_status = _eligibility_status(source_product.raw)
        if eligibility_status == "ineligible":
            negative_evidence.append(
                NormalizationEvidence(
                    kind="catalog_eligibility",
                    result="fail",
                    message="Catalog eligibility check marked the source offer as ineligible.",
                    source_value=eligibility_status,
                )
            )
            return _decision(
                source_product_id=source.id,
                action="quarantine",
                status="data_problem",
                confidence=Decimal("0.000"),
                positive_evidence=positive_evidence,
                negative_evidence=negative_evidence,
                blockers=("catalog_eligibility",),
            )

        if not source.normalized_title:
            negative_evidence.append(
                NormalizationEvidence(
                    kind="title",
                    result="fail",
                    message="Source offer title is empty after normalization.",
                )
            )
            return _decision(
                source_product_id=source.id,
                action="quarantine",
                status="data_problem",
                confidence=Decimal("0.000"),
                positive_evidence=positive_evidence,
                negative_evidence=negative_evidence,
                blockers=("empty_title",),
            )

        if eligibility_status == "needs_review":
            negative_evidence.append(
                NormalizationEvidence(
                    kind="catalog_eligibility",
                    result="warn",
                    message="Catalog eligibility check requires operator review.",
                    source_value=eligibility_status,
                )
            )
            return _decision(
                source_product_id=source.id,
                action="needs_review",
                status="needs_review",
                confidence=Decimal("0.500"),
                positive_evidence=positive_evidence,
                negative_evidence=negative_evidence,
                blockers=("catalog_eligibility",),
            )

        rejected_ids = frozenset(rejected_canonical_product_ids)
        alternatives = tuple(
            sorted(
                (
                    _score_alternative(
                        source,
                        _prepare_canonical(candidate),
                        rejected_canonical_product_ids=rejected_ids,
                    )
                    for candidate in candidates
                ),
                key=lambda alternative: alternative.confidence,
                reverse=True,
            )
        )
        ready_alternatives = tuple(
            alternative for alternative in alternatives if alternative.is_ready
        )
        reviewable_alternatives = tuple(
            alternative for alternative in alternatives if alternative.is_reviewable
        )
        conflicting_alternatives = tuple(
            alternative for alternative in alternatives if alternative.blockers
        )

        if len(ready_alternatives) == 1 and len(reviewable_alternatives) == 1:
            selected = ready_alternatives[0]
            return _decision(
                source_product_id=source.id,
                action="attach_to_existing",
                status="ready_to_accept",
                confidence=selected.confidence,
                positive_evidence=(
                    *positive_evidence,
                    *selected.positive_evidence,
                ),
                negative_evidence=(
                    *negative_evidence,
                    *selected.negative_evidence,
                    NormalizationEvidence(
                        kind="candidate_count",
                        result="pass",
                        message="Exactly one safe canonical candidate is available.",
                        source_value="1",
                    ),
                ),
                canonical_product_id=selected.canonical_product_id,
                canonical_title=selected.canonical_title,
                method=selected.method,
                alternatives=alternatives,
            )

        if ready_alternatives or len(reviewable_alternatives) > 1:
            negative_evidence.append(
                NormalizationEvidence(
                    kind="candidate_count",
                    result="fail",
                    message="More than one reviewable canonical candidate exists.",
                    source_value=str(len(reviewable_alternatives)),
                )
            )
            return _decision(
                source_product_id=source.id,
                action="needs_review",
                status="needs_review",
                confidence=_max_confidence(alternatives, default=Decimal("0.500")),
                positive_evidence=positive_evidence,
                negative_evidence=negative_evidence,
                alternatives=alternatives,
                blockers=("ambiguous_candidates",),
            )

        if reviewable_alternatives or conflicting_alternatives:
            best = reviewable_alternatives[0] if reviewable_alternatives else alternatives[0]
            return _decision(
                source_product_id=source.id,
                action="needs_review",
                status="needs_review",
                confidence=best.confidence,
                positive_evidence=(
                    *positive_evidence,
                    *best.positive_evidence,
                ),
                negative_evidence=(
                    *negative_evidence,
                    *best.negative_evidence,
                ),
                alternatives=alternatives,
                blockers=best.blockers or ("low_confidence_match",),
            )

        source_readiness = _source_creation_readiness(source)
        if source_readiness:
            positive_evidence.extend(source_readiness[0])
            negative_evidence.extend(source_readiness[1])
            return _decision(
                source_product_id=source.id,
                action="create_normalized_product",
                status="ready_to_accept",
                confidence=Decimal("0.970"),
                positive_evidence=positive_evidence,
                negative_evidence=negative_evidence,
                alternatives=alternatives,
            )

        negative_evidence.append(
            NormalizationEvidence(
                kind="source_specificity",
                result="warn",
                message="Source offer lacks enough protected attributes for automatic creation.",
            )
        )
        return _decision(
            source_product_id=source.id,
            action="needs_review",
            status="needs_review",
            confidence=Decimal("0.600"),
            positive_evidence=positive_evidence,
            negative_evidence=negative_evidence,
            alternatives=alternatives,
            blockers=("weak_source_specificity",),
        )


def decide_normalization(
    source_product: NormalizationSourceProductLike,
    *,
    candidates: Iterable[NormalizationCanonicalProductLike] = (),
    rejected_canonical_product_ids: Iterable[int] = (),
) -> NormalizationDecision:
    return NormalizationDecisionEngine().decide(
        source_product,
        candidates=candidates,
        rejected_canonical_product_ids=rejected_canonical_product_ids,
    )


def decide_normalization_batch(
    source_products: Iterable[NormalizationSourceProductLike],
    *,
    candidates_by_source_product_id: Mapping[int, Iterable[NormalizationCanonicalProductLike]],
    rejected_canonical_product_ids_by_source_product_id: Mapping[int, Iterable[int]]
    | None = None,
) -> tuple[NormalizationDecision, ...]:
    engine = NormalizationDecisionEngine()
    rejected_by_source = rejected_canonical_product_ids_by_source_product_id or {}
    return tuple(
        engine.decide(
            source_product,
            candidates=candidates_by_source_product_id.get(source_product.id, ()),
            rejected_canonical_product_ids=rejected_by_source.get(source_product.id, ()),
        )
        for source_product in source_products
    )


def _decision(
    *,
    source_product_id: int,
    action: NormalizationDecisionAction,
    status: NormalizationDecisionStatus,
    confidence: Decimal,
    positive_evidence: Iterable[NormalizationEvidence],
    negative_evidence: Iterable[NormalizationEvidence],
    canonical_product_id: int | None = None,
    canonical_title: str | None = None,
    method: str = "attribute_rules",
    alternatives: tuple[NormalizationAlternative, ...] = (),
    blockers: tuple[str, ...] = (),
) -> NormalizationDecision:
    return NormalizationDecision(
        source_product_id=source_product_id,
        action=action,
        status=status,
        confidence=confidence.quantize(Decimal("0.001")),
        canonical_product_id=canonical_product_id,
        canonical_title=canonical_title,
        method=method,
        positive_evidence=tuple(positive_evidence),
        negative_evidence=tuple(negative_evidence),
        alternatives=alternatives,
        blockers=blockers,
    )


def _prepare_source(source_product: NormalizationSourceProductLike) -> _PreparedProduct:
    extraction = extract_product_attributes(
        source_product.title,
        source=source_product.source,
        category_raw=source_product.category_raw,
    )
    return _PreparedProduct(
        id=source_product.id,
        title=source_product.title,
        normalized_title=source_product.normalized_title
        or normalize_title(source_product.title),
        category_id=source_product.category_id,
        category_raw=source_product.category_raw,
        unit_raw=source_product.unit_raw,
        tokens=_tokens(source_product.normalized_title or source_product.title),
        attributes=extraction.attributes,
        extraction_reasons=extraction.reasons,
        extraction_confidence=extraction.confidence,
    )


def _prepare_canonical(
    canonical_product: NormalizationCanonicalProductLike,
) -> _PreparedProduct:
    extraction = extract_product_attributes(canonical_product.title)
    return _PreparedProduct(
        id=canonical_product.id,
        title=canonical_product.title,
        normalized_title=canonical_product.normalized_title
        or normalize_title(canonical_product.title),
        category_id=canonical_product.category_id,
        category_raw=None,
        unit_raw=canonical_product.unit_raw,
        tokens=_tokens(canonical_product.normalized_title or canonical_product.title),
        attributes=extraction.attributes,
        extraction_reasons=extraction.reasons,
        extraction_confidence=extraction.confidence,
    )


def _tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in tokenize_normalized_text(normalize_title(value))
        if token not in _LOW_VALUE_TOKENS
    )


def _source_positive_evidence(
    source: _PreparedProduct,
    source_product: NormalizationSourceProductLike,
) -> tuple[NormalizationEvidence, ...]:
    evidence = [
        NormalizationEvidence(
            kind="title",
            result="pass",
            message="Source offer has a normalized title.",
            source_value=source.normalized_title,
        )
    ]
    eligibility_status = _eligibility_status(source_product.raw)
    if eligibility_status in {None, "eligible"}:
        evidence.append(
            NormalizationEvidence(
                kind="catalog_eligibility",
                result="pass",
                message="Catalog eligibility allows automated normalization checks.",
                source_value=eligibility_status or "missing",
            )
        )
    if source.category_id is not None:
        evidence.append(
            NormalizationEvidence(
                kind="category",
                result="pass",
                message="Source offer has a normalized category.",
                source_value=str(source.category_id),
            )
        )
    if source.attributes:
        evidence.append(
            NormalizationEvidence(
                kind="attributes",
                result="pass",
                message="Source offer has extracted protected attributes.",
                source_value=", ".join(_attribute_labels(source.attributes)),
            )
        )
    return tuple(evidence)


def _source_negative_evidence(
    source: _PreparedProduct,
    source_product: NormalizationSourceProductLike,
) -> tuple[NormalizationEvidence, ...]:
    evidence: list[NormalizationEvidence] = []
    if not source_product.is_not_product:
        evidence.append(
            NormalizationEvidence(
                kind="source_product_flag",
                result="pass",
                message="Source offer is not marked as non-product.",
            )
        )
    if source.category_id is None:
        evidence.append(
            NormalizationEvidence(
                kind="category",
                result="warn",
                message="Source offer has no normalized category.",
            )
        )
    if not source.attributes:
        evidence.append(
            NormalizationEvidence(
                kind="attributes",
                result="warn",
                message="No protected attributes were extracted from the title.",
            )
        )
    for reason in source.extraction_reasons:
        if reason.startswith("noise:"):
            evidence.append(
                NormalizationEvidence(
                    kind="title_noise",
                    result="warn",
                    message="Title contains source or offer noise.",
                    source_value=reason,
                )
            )
    return tuple(evidence)


def _score_alternative(
    source: _PreparedProduct,
    candidate: _PreparedProduct,
    *,
    rejected_canonical_product_ids: frozenset[int],
) -> NormalizationAlternative:
    positive_evidence: list[NormalizationEvidence] = []
    negative_evidence: list[NormalizationEvidence] = []
    blockers: list[str] = []

    same_category = _same_category(source, candidate)
    if same_category is True:
        positive_evidence.append(
            NormalizationEvidence(
                kind="category",
                result="pass",
                message="Source and canonical categories match.",
                source_value=str(source.category_id),
                target_value=str(candidate.category_id),
            )
        )
    elif same_category is False:
        blockers.append("category_mismatch")
        negative_evidence.append(
            NormalizationEvidence(
                kind="category",
                result="fail",
                message="Source and canonical categories conflict.",
                source_value=str(source.category_id),
                target_value=str(candidate.category_id),
            )
        )
    else:
        negative_evidence.append(
            NormalizationEvidence(
                kind="category",
                result="warn",
                message="Category comparison is incomplete.",
                source_value=_optional_id(source.category_id),
                target_value=_optional_id(candidate.category_id),
            )
        )

    exact_title = source.normalized_title == candidate.normalized_title
    token_similarity = _jaccard(source.tokens, candidate.tokens)
    if exact_title:
        confidence = Decimal("1.000")
        method = "exact_normalized_title"
        positive_evidence.append(
            NormalizationEvidence(
                kind="title",
                result="pass",
                message="Normalized titles are identical.",
                source_value=source.normalized_title,
                target_value=candidate.normalized_title,
            )
        )
    else:
        confidence = _decimal_similarity(token_similarity)
        method = "token_similarity"
        positive_evidence.append(
            NormalizationEvidence(
                kind="title_similarity",
                result="pass" if confidence >= _REVIEW_CONFIDENCE else "warn",
                message="Normalized title token similarity was evaluated.",
                source_value=str(confidence),
            )
        )

    attribute_matches, attribute_conflicts = _attribute_comparison(
        source.attributes,
        candidate.attributes,
    )
    if attribute_matches:
        positive_evidence.append(
            NormalizationEvidence(
                kind="attributes",
                result="pass",
                message="Protected attributes match.",
                source_value=", ".join(attribute_matches),
            )
        )
        confidence = min(
            Decimal("1.000"),
            confidence + Decimal("0.050") * min(len(attribute_matches), 3),
        )
    else:
        negative_evidence.append(
            NormalizationEvidence(
                kind="attributes",
                result="warn",
                message="No matching protected attributes were found.",
            )
        )

    for kind, source_value, target_value in attribute_conflicts:
        blockers.append(f"{kind}_conflict")
        negative_evidence.append(
            NormalizationEvidence(
                kind="attribute_conflict",
                result="fail",
                message=f"Protected attribute '{kind}' conflicts.",
                source_value=source_value,
                target_value=target_value,
            )
        )

    unit_conflict = _unit_conflict(source.unit_raw, candidate.unit_raw)
    if unit_conflict is not None:
        source_unit, target_unit = unit_conflict
        blockers.append("unit_conflict")
        negative_evidence.append(
            NormalizationEvidence(
                kind="unit",
                result="fail",
                message="Selling units conflict.",
                source_value=source_unit,
                target_value=target_unit,
            )
        )

    if candidate.id in rejected_canonical_product_ids:
        blockers.append("operator_rejected")
        negative_evidence.append(
            NormalizationEvidence(
                kind="operator_override",
                result="fail",
                message="Operator previously rejected this canonical candidate.",
                target_value=str(candidate.id),
            )
        )

    if blockers:
        confidence = min(confidence, Decimal("0.690"))
    elif same_category is None:
        confidence *= Decimal("0.950")

    if not negative_evidence:
        negative_evidence.append(
            NormalizationEvidence(
                kind="conflict_check",
                result="pass",
                message="No blocking conflicts were detected.",
            )
        )

    return NormalizationAlternative(
        canonical_product_id=candidate.id,
        canonical_title=candidate.title,
        confidence=confidence.quantize(Decimal("0.001")),
        method=method,
        positive_evidence=tuple(positive_evidence),
        negative_evidence=tuple(negative_evidence),
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _source_creation_readiness(
    source: _PreparedProduct,
) -> tuple[list[NormalizationEvidence], list[NormalizationEvidence]] | None:
    positive: list[NormalizationEvidence] = []
    negative: list[NormalizationEvidence] = [
        NormalizationEvidence(
            kind="candidate_count",
            result="pass",
            message="No existing canonical candidates need review.",
            source_value="0",
        )
    ]
    if source.category_id is None:
        return None
    if source.extraction_confidence < Decimal("0.700"):
        return None

    specific_attributes = tuple(
        attribute for attribute in source.attributes if attribute.kind in _SPECIFIC_ATTRIBUTE_KINDS
    )
    has_numeric_token = any(any(char.isdigit() for char in token) for token in source.tokens)
    if not specific_attributes and not has_numeric_token:
        return None

    if specific_attributes:
        positive.append(
            NormalizationEvidence(
                kind="source_specificity",
                result="pass",
                message="Source title is specific enough for a new normalized product.",
                source_value=", ".join(_attribute_labels(specific_attributes)),
            )
        )
    else:
        positive.append(
            NormalizationEvidence(
                kind="source_specificity",
                result="pass",
                message="Source title contains protected numeric tokens.",
            )
        )
    return positive, negative


def _same_category(left: _PreparedProduct, right: _PreparedProduct) -> bool | None:
    if left.category_id is not None and right.category_id is not None:
        return left.category_id == right.category_id
    return None


def _attribute_comparison(
    source_attributes: tuple[ExtractedAttribute, ...],
    target_attributes: tuple[ExtractedAttribute, ...],
) -> tuple[tuple[str, ...], tuple[tuple[str, str, str], ...]]:
    source = _attribute_signatures_by_kind(source_attributes)
    target = _attribute_signatures_by_kind(target_attributes)
    matches: list[str] = []
    conflicts: list[tuple[str, str, str]] = []

    for kind in sorted(_PROTECTED_ATTRIBUTE_KINDS):
        source_values = source.get(kind)
        target_values = target.get(kind)
        if not source_values or not target_values:
            continue
        overlap = source_values & target_values
        if overlap:
            matches.append(f"{kind}:{sorted(overlap)[0]}")
        elif source_values.isdisjoint(target_values):
            conflicts.append(
                (
                    kind,
                    ", ".join(sorted(source_values)),
                    ", ".join(sorted(target_values)),
                )
            )

    return tuple(matches), tuple(conflicts)


def _attribute_signatures_by_kind(
    attributes: tuple[ExtractedAttribute, ...],
) -> dict[str, set[str]]:
    signatures: dict[str, set[str]] = {}

    for attribute in attributes:
        if attribute.kind not in _PROTECTED_ATTRIBUTE_KINDS:
            continue
        signature = _attribute_signature(attribute)
        if signature is not None:
            signatures.setdefault(attribute.kind, set()).add(signature)

    return signatures


def _attribute_signature(attribute: ExtractedAttribute) -> str | None:
    if attribute.normalized is not None:
        return attribute.normalized
    if attribute.values:
        values = "x".join(str(value.normalize()) for value in attribute.values)
        return f"{values}{attribute.unit}"
    return None


def _attribute_labels(attributes: Iterable[ExtractedAttribute]) -> tuple[str, ...]:
    return tuple(
        f"{attribute.kind}:{_attribute_signature(attribute) or attribute.raw}"
        for attribute in attributes
    )


def _unit_conflict(
    source_unit: str | None,
    target_unit: str | None,
) -> tuple[str, str] | None:
    if not source_unit or not target_unit:
        return None
    normalized_source = normalize_title(source_unit)
    normalized_target = normalize_title(target_unit)
    if normalized_source == normalized_target:
        return None
    return normalized_source, normalized_target


def _eligibility_status(raw: JsonObject | None) -> str | None:
    if raw is None:
        return None
    value = raw.get("catalog_eligibility")
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    if status is None:
        return None
    return str(status)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 0.0
    return len(left & right) / len(left | right)


def _decimal_similarity(value: float) -> Decimal:
    return Decimal(str(round(value, 3))).quantize(Decimal("0.001"))


def _max_confidence(
    alternatives: tuple[NormalizationAlternative, ...],
    *,
    default: Decimal,
) -> Decimal:
    if not alternatives:
        return default
    return max(alternative.confidence for alternative in alternatives)


def _optional_id(value: int | None) -> str | None:
    if value is None:
        return None
    return str(value)
