# Category Predictor Pipeline

This document defines the future category predictor/proposer flow. The design is
for post-MVP ML work: MVP behavior must keep using deterministic category rules,
manual overrides, quality queues, and operator review.

## Roles

The category system has three separate responsibilities.

`Rule/alias categorizer` is the production baseline. It maps source products to
categories from source category mappings, taxonomy keywords, and deterministic
text rules. It must stay explainable and available without ML artifacts.

`Category predictor` is a proposer. Given one source product, it returns a
ranked list of likely existing leaf categories. It does not decide whether a
category is correct, does not create categories, and does not mutate
`source_products.category_id`.

`Category verifier` is a pairwise checker. Given one source product and one
candidate category, it returns whether the product fits that category. The
verifier can reject or downgrade predictor proposals before they reach operator
review.

## Predictor Input

The predictor input is one active source product plus the current category
taxonomy context.

Product fields:

- `source_product_id`
- `source`
- `shop_id`
- `shop_name`
- `title`
- `normalized_title`
- `description`
- `category_raw`
- `unit_raw`
- extracted/protected attributes when available
- current `category_id`, if rule/manual categorization already assigned one
- catalog quality stage/reasons when available

Category fields:

- existing normalized category `id`
- `slug`
- `name`
- `parent_id`
- full category path
- whether the category is a leaf
- taxonomy keywords or aliases when available

The predictor may use source/shop context and source category mappings as
features, but output candidates must still be existing normalized leaf
categories.

## Predictor Output Contract

Default output is top 3 leaf categories. Implementations may compute more
internally, but admin/API surfaces should start with a small ranked set.

```python
CategoryPredictionResult(
    source_product_id=int,
    generated_at=datetime,
    predictor_version=str,
    method="rule_keyword" | "source_mapping" | "trained_model" | "hybrid",
    candidates=(
        CategoryPredictionCandidate(
            category_id=int,
            category_slug=str,
            category_name=str,
            category_path=tuple[str, ...],
            rank=int,
            score=Decimal,
            reasons=tuple[str, ...],
            evidence=dict[str, object] | None,
        ),
        ...
    ),
)
```

Contract rules:

- `candidates` must contain only existing leaf categories.
- Candidate IDs must be unique.
- `rank` starts at 1 and follows descending `score`.
- Scores are comparable only within one predictor version.
- Reasons must be operator-readable, for example source category match, keyword
  hit, or similar accepted operator decisions.
- Empty candidates are valid and mean "no confident proposal".
- Parent categories are never returned as final proposals. If a parent category
  is the strongest signal, the predictor should rank likely child/leaf
  categories under it or return no confident proposal.

## Verifier Handoff

The predictor does not write suggestions directly. The category flow evaluates
each predictor candidate with the verifier.

```text
source product
  -> predictor top-N leaf candidates
  -> verifier checks product/category pairs
  -> routing decision
  -> admin review or no suggestion
```

For each candidate, the verifier adds:

- `verifier_decision`: `match`, `no_match`, or `uncertain`;
- `verifier_confidence`;
- `verifier_version`;
- verifier reasons or feature evidence when available.

Routing rules:

- If no predictor candidates exist, send the product to category review without
  a confident suggestion.
- If the top candidate is a verifier `match`, expose it as the primary
  suggestion with the remaining candidates as alternatives.
- If multiple candidates are verifier `match` and close in score, route to human
  review with all matched candidates visible.
- If the verifier returns `uncertain` for the top candidate, route to review.
- If all candidates are verifier `no_match`, route to review with "no confident
  suggestion"; do not silently keep the best rejected candidate.
- Active manual category overrides take precedence over predictor output.
- Products marked `is_not_product` are not sent to predictor/verifier.

Until a later release decision changes this, predictor/verifier output is review
evidence only. It must not auto-change categories.

## Operator Decisions and Labels

Admin category actions are the production source of learning signals because
they record the actual evidence and alternatives shown to the operator in
`operator_decisions`.

Accepted category suggestion:

- writes/updates the effective category through the normal category override
  path;
- records a `categorization` operator decision;
- becomes a positive predictor target for that source product/category;
- becomes a verifier `match` label for the accepted product/category pair.

Rejected suggestion:

- records a `categorization` operator decision with the rejected candidate in
  evidence/alternatives;
- becomes a verifier `no_match` label for the rejected pair;
- does not create a positive predictor target unless the operator chooses a
  replacement category.

Operator-chosen replacement category:

- becomes the positive predictor target;
- the shown but unselected candidates become verifier `no_match` examples when
  they were explicit alternatives.

The existing CLI label store may still be used for offline experiments. When
training from both CLI labels and `operator_decisions`, datasets must preserve
label provenance so evaluation can distinguish experimental labels from real
admin review decisions.

## Review Queue Shape

The admin/API suggestion payload should be task-oriented:

```json
{
  "source_product_id": 123,
  "title": "Цемент М500 50 кг",
  "current_category_id": null,
  "primary_suggestion": {
    "category_id": 45,
    "category_path": ["Строительные материалы", "Цемент"],
    "predictor_score": "0.92",
    "verifier_decision": "match",
    "verifier_confidence": "0.86",
    "reasons": ["source category matched", "title contains цемент"]
  },
  "alternatives": [],
  "status": "needs_review"
}
```

Suggested statuses:

- `needs_review`: operator action required.
- `accepted`: operator accepted the suggestion.
- `rejected`: operator rejected the suggestion.
- `superseded`: a newer source product state or manual decision replaced it.
- `expired`: source product changed enough that the suggestion should be
  regenerated.

## Evaluation

Predictor evaluation uses products with accepted category decisions.

Required predictor metrics:

- label count;
- prediction count and missing prediction count;
- top-1 accuracy;
- top-3 accuracy;
- mean reciprocal rank;
- coverage: share of eligible products with at least one candidate;
- per-source and per-top-level-category breakdowns.

Required verifier-gated metrics:

- accepted-suggestion precision;
- rejected-suggestion recall where rejected alternatives are available;
- uncertain rate;
- unsafe suggestion count: cases where the predictor top candidate would have
  been accepted by automation but the operator rejected or replaced it.

No trained predictor should be used for production suggestions until it beats
the deterministic rule proposer on held-out operator decisions and has an
acceptable unsafe-suggestion rate. It must not enable auto-accept without a
separate release decision.

## Implementation Tasks

1. Add `packages/stroyhub/ml/predictor.py` with dataclasses for the input and
   output contract above.
2. Implement a rule-backed predictor adapter that wraps current source category
   mappings and taxonomy keyword categorization, returning top-N leaf category
   proposals with reasons.
3. Add offline evaluation helpers for `CategoryDecisionExample` using top-1,
   top-3, MRR, coverage, and per-source breakdowns.
4. Add a suggestion persistence design or table before exposing suggestions in
   admin API. Reuse `operator_decisions` for decisions, but do not use it as the
   queue storage itself.
5. Add an admin API endpoint for category suggestion queues only after
   persistence is clear.
6. Add admin review UI that shows the primary suggestion, alternatives,
   predictor reasons, verifier decision, and the normal accept/reject/choose
   other actions.
7. Train a first model only after enough operator decisions exist to evaluate it
   against the rule-backed predictor baseline.

