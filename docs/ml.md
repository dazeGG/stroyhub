# ML Workspace

StroyHub ML work is separated from the operational admin app. The admin app is
for catalog operations and human review. The ML workspace is for building
datasets, training models, evaluating them, and managing model artifacts.

## Boundaries

- `apps/ml` owns CLI commands for labeling, dataset snapshots, training,
  evaluation, reports, and model artifact management.
- `packages/stroyhub/ml` owns reusable ML code: feature builders, model
  metadata readers, public verifier/predictor APIs, and runtime loaders.
- `apps/api` and `apps/worker` may load ready model artifacts through
  `packages/stroyhub/ml`; they must not train models or import sklearn/joblib
  internals directly.
- `apps/admin` stays operational. It can review category suggestions exposed by
  the API, but it does not collect training labels or manage model files.
- No `stroyhub_ml` package is introduced.

## Runtime Artifacts

ML runtime data is stored under `.var/ml` in the repository root. `.var/` is
ignored by git.

```text
.var/ml/
  category_verifier/
    labels.jsonl
    datasets/
      v001.jsonl
      v001.meta.json
    models/
      v001/
        model.joblib
        metadata.json
      current -> v001
    reports/
      errors/
        v001.jsonl
```

Git should contain code, docs, tests, small fixtures when needed, and metadata
schemas. Git should not contain collected labels, dataset snapshots, trained
models, generated reports, or local database-derived product data.

## CLI Labeling

The first labeling workflow is CLI-first. It reads products and categories
directly from PostgreSQL through StroyHub DB/session helpers and writes labels
to `.var/ml/category_verifier/labels.jsonl`.

Each labeling item shows one source product and three candidate leaf categories.
The operator can choose:

- one category;
- multiple categories;
- nothing fits;
- skip;
- quit.

Selected categories become verifier `match` labels. Candidate categories that
were shown but not selected become verifier `no_match` labels. Selected
categories are also recorded as positive targets for the future category
predictor. If the operator chooses nothing fits, all shown candidates become
verifier `no_match` labels and the product receives no positive predictor
target for that item.

Labels do not directly mutate `source_products.category_id`. They train models.
Operational category changes still go through manual category overrides or
accepted suggestions.

The queue generator is deterministic for tests and repeatable CLI sessions. It
prefers the current product category when it is a leaf, then rule/text signals,
then nearby categories with the same parent, then stable fallback leaf
categories. Product/category pairs already present in `labels.jsonl` are skipped
when selecting candidates.

## Live Labels and Snapshots

`labels.jsonl` is the live append-only label log. Dataset snapshots are frozen
files created from the live log before training. A snapshot is not created for
every individual label.

The category verifier dataset CLI exposes the current workflow:

```bash
uv run python -m apps.ml.category_verifier_dataset_cli status
uv run python -m apps.ml.category_verifier_dataset_cli snapshot
```

`status` compares the live label log with the latest snapshot and reports total
live labels, total live labeled products, latest snapshot counts, new labels,
new labeled products, and `ready_for_training`. Readiness is true when at least
50 newly labeled products exist since the latest snapshot. If no snapshot exists,
the live labeled product count is used as the new count.

`snapshot` creates the next incrementing dataset version under
`.var/ml/category_verifier/datasets/`, for example `v001.jsonl` with
`v001.meta.json`. Metadata records the snapshot version, creation time, source
label file, schema version, label count, and labeled product count.

Duplicate product/category pair labels are allowed as later corrections in the
append-only log. Dataset helpers use the latest label for a product/category
pair by default, while CLI queue helpers can skip pairs that already have any
label.

Training uses the latest snapshot. The planned training command creates the next
snapshot version automatically before fitting a model. It should refuse to train
unless there are at least 50 newly labeled products since the latest snapshot,
unless `--force` is passed.

The train/evaluate pipeline is one command: training runs first, then evaluation
runs against the held-out split and writes reports. Evaluation is not a normal
standalone production command for the MVP.

The train/evaluation split is 80/20 by product id. The random seed is derived
from the pipeline run date in `YYYYMMDD` form and saved in snapshot/model
metadata.

The first training implementation is intentionally a small token baseline, not
a neural network. It is trained by:

```bash
uv run python -m apps.ml.category_verifier_train_cli
```

The command checks whether at least 50 newly labeled products exist since the
latest snapshot, unless `--force` is passed. It then creates the next snapshot,
splits labels by product id into train/evaluation sets, trains the verifier,
evaluates only on held-out labels, writes metrics and split metadata into
`models/vNNN/metadata.json`, writes the model artifact to `model.joblib`, writes
held-out mistakes or uncertain decisions to `reports/errors/vNNN.jsonl`, and
updates `models/current` only after training and evaluation complete.

## Category Verifier

The category verifier answers one question: does this product fit this category?
It is a small supervised model or algorithm trained from labels. Its public
runtime API should look like:

```python
verifier.verify(product, category)
```

The verifier returns a decision and confidence. Thresholds are stored in model
metadata. Current planned thresholds are:

- `match`: confidence is at least `0.80`;
- `no_match`: confidence is at most `0.35`;
- `uncertain`: everything in between.

The shared feature builder used during training must also be used at runtime.
This keeps training behavior and production behavior aligned.

Feature building lives in `packages/stroyhub/ml/features.py`. The verifier
feature contract is versioned as `category_verifier_features/v1` and turns one
product/category pair into deterministic string features. The current contract
includes product source, shop id, title, normalized title, raw source category,
description, candidate category id, slug, name, parent id, category path names
and slugs, combined product/category context text, and simple pair flags such as
whether the product's current category is the candidate and whether product text
mentions the category. Training and runtime verification must import this shared
builder instead of recreating feature strings separately.

## Category Predictor

The future category predictor proposes likely categories for a product. It can
reuse the same labels collected by the verifier CLI:

- selected categories are positive predictor targets;
- nothing fits means no positive target for that product/item.

The predictor should return top candidate leaf categories, for example top
three. The verifier then checks each proposed product/category pair. Predictor
work is tracked separately from the verifier MVP.

## Suggestion Review Flow

Suggestions are operational review records, not training labels. They are for
new or changed source products where automated category logic proposes a
category and a human should accept or correct it.

Flow:

1. Scraping persists the source product and price snapshot.
2. Rule/alias categorization can produce a baseline category.
3. The predictor proposes one or more existing leaf categories.
4. The verifier checks proposed product/category pairs.
5. The system stores a category suggestion instead of trusting ML immediately.
6. Admin review shows suggestions that need human action.
7. A reviewer accepts, rejects, or chooses another existing leaf category.
8. Accepted decisions update the effective product category through manual
   category override persistence and may later become training examples.

Suggested statuses:

- `needs_accept`: ready for human review.
- `accepted`: reviewer accepted the suggestion.
- `rejected`: reviewer rejected the suggestion.
- `superseded`: a newer suggestion or manual decision replaced it.
- `expired`: source product changed enough that the old suggestion should no
  longer be reviewed.

Suggestions must target existing normalized leaf categories. They must not
create categories automatically. Active manual category overrides have higher
operational precedence than suggestions.
