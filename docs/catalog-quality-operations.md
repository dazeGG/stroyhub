# Catalog Quality Operations

M16 rebuilds StroyHub's admin and normalization work around a catalog-quality
pipeline. The goal is to turn source shop cards into a public catalog that can
be trusted for price comparison.

This document is the contract for follow-up admin API, worker, admin UI, and ML
work. It defines operator-facing states first, then maps them to implementation
concerns where needed.

## Product Goal

StroyHub should answer a buyer's practical question:

> What is this construction material, where is it sold, and which offer is
> trustworthy enough to compare?

The admin service exists to keep that answer reliable. Operators should not work
through database entities. They should work through queues that say what needs
attention and why.

## Operator Vocabulary

Use these terms in admin navigation, queue names, dashboard cards, and primary
actions:

| Term | Meaning |
| --- | --- |
| New item | A shop offer was collected or changed and has not finished catalog checks. |
| Ready to accept | The system has enough evidence to safely add or attach the offer. |
| Needs review | The system found a plausible result, but there is ambiguity or conflict. |
| Data problem | The offer is too incomplete, noisy, or stale to safely use in the catalog. |
| In catalog | The offer is accepted into a normalized catalog product. |
| Possible duplicate | Two normalized catalog products may describe the same material. |

Avoid using `canonical`, `match`, `candidate`, `source_product`, or table names
as primary UI language. Those names may still exist in code, database schema,
and debug panels.

## Lifecycle States

Each observed offer moves through the following conceptual states. The state may
be stored directly later, or derived from existing tables and timestamps during
the transition period.

| State | Entry condition | Exit condition | Normal owner |
| --- | --- | --- | --- |
| `collected` | A parser persisted or updated a shop offer and price observation. | The cleanup gate starts. | Worker |
| `cleaned` | Basic title, unit, price, source, and shop checks passed. | Attribute extraction and categorization finish. | Worker |
| `categorized` | The system chose a catalog category or produced category evidence. | Normalization decisioning finishes. | Worker |
| `ready_to_accept` | The decision engine found a safe create/attach action with no blockers. | Batch or single accept applies the decision. | Operator or worker-assisted admin action |
| `needs_review` | The system found competing possibilities, weak evidence, or important conflicts. | Operator chooses attach, create, reject, fix category, or mark as data problem. | Operator |
| `data_problem` | Required evidence is missing, inconsistent, stale, or parser output is suspect. | Source/parser/category data is fixed and checks are re-run, or item is intentionally ignored. | Operator or developer |
| `in_catalog` | The offer is accepted into a normalized catalog product. | Later quality checks find a conflict, duplicate, stale source, or manual correction. | System |
| `quality_issue` | A background check found a problem after acceptance. | Operator/developer resolves the underlying data and re-runs checks. | Operator or developer |

`ready_to_accept`, `needs_review`, and `data_problem` are mutually exclusive
operator queues. An item should never appear as ready to accept and needs review
at the same time.

## Quality Gates

Each gate returns:

- `status`: pass, review, or problem;
- `confidence`: numeric score when useful;
- `evidence`: structured facts that support the decision;
- `blockers`: structured facts that prevent safe automation;
- `next_action`: the recommended queue/action.

### 1. Collection Gate

Purpose: confirm that the parser produced a usable observation.

Pass when:

- title is present;
- shop/source identity is known;
- source identity or fallback fingerprint is available;
- latest observation timestamp is present;
- price is either valid or explicitly absent for a known reason.

Review/problem when:

- title is empty or generic;
- source identity is unstable;
- price cannot be parsed but should exist;
- the source reports a broad catalog group instead of a product offer.

### 2. Cleanup Gate

Purpose: normalize text and extract product facts before category or product
decisions.

Pass when:

- title normalization succeeds;
- unit text is preserved and, when possible, normalized;
- obvious shop/source noise is removed from comparison text;
- dimensions, package size, grade, brand, or model are extracted when present.

Review/problem when:

- extracted facts conflict with each other;
- title appears to describe a service, group, or non-product;
- the parser put category, price, or availability text into the title.

### 3. Categorization Gate

Purpose: decide which catalog category can own the item.

Pass when:

- category is a product leaf category;
- evidence is strong enough from source category, title rules, aliases, or
  extracted attributes;
- no active manual override conflicts with the proposed category.

Review/problem when:

- only a root/group category is available;
- multiple unrelated leaf categories score closely;
- source category and title evidence disagree;
- the item is outside the construction-material catalog scope.

### 4. Normalization Gate

Purpose: decide whether the item should create a normalized product, attach to
an existing normalized product, or go to review.

Pass when:

- category is compatible;
- required category-specific attributes agree;
- protected attributes do not conflict;
- confidence is above the auto-accept threshold;
- accepting this item would not create a competing review case elsewhere.

Review when:

- several existing catalog products are plausible;
- important attributes are missing but title similarity is high;
- category is compatible but package, dimensions, grade, color, or brand are
  ambiguous;
- the item is similar to a recently created catalog product that needs human
  confirmation.

Problem when:

- hard blockers conflict, such as different dimensions, package size, grade, or
  product type;
- the offer is too broad to normalize;
- the data cannot support a safe catalog product.

### 5. Acceptance Gate

Purpose: keep batch actions safe.

Before any single or batch accept, re-run the current decision contract. Apply
only items that still pass. Skip every item that has moved to review or problem,
and return the skip reason to the admin UI.

Batch acceptance must never silently accept:

- items currently assigned to review;
- items with changed category or attributes since preview;
- items whose acceptance would make another visible item require review;
- items with stale evidence.

### 6. Continuous Quality Gate

Purpose: find problems after items are already in the catalog.

Checks should detect:

- possible duplicate normalized products;
- accepted offers with conflicting protected attributes;
- stale prices or stale source shops;
- products missing category-critical attributes;
- categories with unusual price or title patterns;
- parser/source regressions that create many data problems.

Quality findings should be idempotent. A finding disappears when the underlying
data is fixed or an explicit reviewed decision supersedes it.

## Protected Attributes

Protected attributes are facts that should usually block automatic attachment
when they conflict. The exact list is category-specific, but M16 starts with:

| Attribute | Examples | Default behavior |
| --- | --- | --- |
| Dimensions | `2500x1250x9 mm`, `100x100x6000 mm` | Conflict blocks auto-accept. |
| Package size | `25 kg`, `50 kg`, `10 l` | Conflict blocks auto-accept. |
| Grade/class | `M400`, `M500`, `OSB-3`, `C8` | Conflict blocks auto-accept. |
| Product type | cement vs plaster, OSB vs plywood | Conflict blocks auto-accept. |
| Brand/model | KNAUF Rotband vs KNAUF Fliesen | Conflict usually blocks unless category rules allow brandless grouping. |
| Color/finish | graphite vs beige siding | Conflict blocks finish-material auto-accept. |

Missing protected attributes do not always block creation of a new normalized
product, but they should reduce confidence and may require review before
attaching to an existing product.

## Operator Actions

Actions should be phrased as work outcomes:

| Action | Allowed from | Effect |
| --- | --- | --- |
| Accept | Ready to accept | Creates or attaches the normalized catalog product using the current decision. |
| Accept selected | Ready to accept | Applies only items that still pass the acceptance gate; reports skipped items. |
| Attach to existing | Needs review | Links the offer to the chosen normalized product and records evidence. |
| Create new product | Needs review or ready to accept | Creates a new normalized product and accepts the offer into it. |
| Reject suggestion | Needs review | Marks the proposed relationship as not valid and keeps/returns the item for another decision. |
| Fix category | Needs review or data problem | Stores an audited category correction and re-runs downstream gates. |
| Mark as data problem | Any pre-catalog state | Stops automation until source/parser/category data is fixed or intentionally ignored. |
| Re-run checks | Data problem or quality issue | Reprocesses the item with current rules and source data. |
| Resolve quality issue | Quality issue | Closes/supersedes a finding after the underlying data is corrected. |

Every mutating action must record actor, timestamp, previous state, new state,
decision reason, and the evidence shown to the operator.

## Explanation Contract

The admin API should return enough evidence for the UI to explain a decision
without reimplementing scoring in the browser.

Recommended shape:

```json
{
  "status": "ready_to_accept",
  "recommended_action": "attach_to_existing",
  "confidence": 0.982,
  "summary": "Same category, dimensions, thickness, and normalized title.",
  "evidence": [
    {
      "kind": "category",
      "label": "Category agrees",
      "value": "Sheet materials / OSB"
    },
    {
      "kind": "attribute",
      "label": "Thickness",
      "source_value": "9 mm",
      "catalog_value": "9 mm",
      "result": "agree"
    }
  ],
  "blockers": [],
  "alternatives": [
    {
      "catalog_product_id": 123,
      "title": "OSB-3 2500x1250x9 mm",
      "confidence": 0.982
    }
  ]
}
```

Evidence should be split into positive evidence, weak/missing evidence, and hard
blockers. UI can render those groups differently, but the backend owns the
meaning.

## Admin Information Architecture

M16 admin navigation should be task-first:

1. Quality dashboard
2. Sources
3. Processing queues
4. Review workspace
5. Categorization
6. Normalized catalog
7. Data problems

The normalized catalog is the result view. Review cases and rejected
relationships should not be presented as part of the main normalized-product
list. If an accepted product has a problem, show that as a quality issue and
link to the review workspace.

## Worker Contract

After a source scrape persists observations, workers should run the catalog
pipeline in separate retry-safe stages:

1. collect/persist source observations;
2. clean and extract attributes;
3. categorize;
4. produce normalization decisions;
5. apply safe automatic actions only when policy allows it;
6. create or refresh quality findings;
7. update queue/dashboard counters.

Stages must be idempotent. Re-running a stage should update the current
decision or supersede stale findings, not create duplicate accepted records.

## ML Position

M16 should capture training/evaluation data, but production decisions remain
explainable and rule-gated.

Allowed in M16:

- store operator choices and alternatives shown;
- design category predictor input/output contracts;
- evaluate future predictors offline;
- use ML suggestions as review evidence.

Evaluation datasets are derived from audited operator decisions:

- categorization examples use accepted category override decisions and the
  category alternatives shown to the operator;
- normalization examples use accepted and rejected match decisions, including
  evidence, blockers, alternatives, and final action.

Future category predictors should report top-1 and top-N category accuracy.
Future normalization predictors should report precision, recall, and unsafe
auto-accept rate. An auto-accept is unsafe when the evaluated label disagrees,
protected safety checks did not pass, or the predictor cannot provide an
explainable decision contract.

Graduating from rules to trained models requires:

- enough recent operator decisions to build a representative evaluation set;
- stable offline metrics across several snapshots;
- explainable evidence that can be shown in the admin review workspace;
- protected-attribute checks outside the model output;
- an explicit follow-up decision linked to the category predictor design issue
  [#165](https://github.com/dazeGG/stroyhub/issues/165).

Not allowed without a later decision:

- black-box auto-accept without protected-attribute checks;
- hidden category changes that bypass audited operator decisions;
- model training or labels as a required production runtime dependency.

## Follow-Up Issue Mapping

- [#296](https://github.com/dazeGG/stroyhub/issues/296): structured attribute extraction.
- [#297](https://github.com/dazeGG/stroyhub/issues/297): explainable normalization engine.
- [#298](https://github.com/dazeGG/stroyhub/issues/298): category rules and source-category mapping.
- [#299](https://github.com/dazeGG/stroyhub/issues/299): worker pipeline.
- [#300](https://github.com/dazeGG/stroyhub/issues/300): workflow queue admin API.
- [#301](https://github.com/dazeGG/stroyhub/issues/301): task-first admin navigation.
- [#302](https://github.com/dazeGG/stroyhub/issues/302): review workspace.
- [#303](https://github.com/dazeGG/stroyhub/issues/303): continuous quality checks.
- [#304](https://github.com/dazeGG/stroyhub/issues/304): operator decision history for ML.
- [#305](https://github.com/dazeGG/stroyhub/issues/305): end-to-end acceptance scenario.
