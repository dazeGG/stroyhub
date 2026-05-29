# StroyHub ML Workspace

`apps/ml` is the command workspace for dataset labeling, dataset snapshots,
training, evaluation, reports, and model artifact management.

CLI commands are grouped by model:

```text
apps/ml/
  category_verifier/
    label_cli.py
    dataset_cli.py
    train_cli.py
  patron/
    label_cli.py
    train_cli.py
```

Planned commands:

- category verifier labeling CLI: `category_verifier.label_cli`;
- category verifier dataset status: `category_verifier.dataset_cli status`;
- category verifier snapshot/export: `category_verifier.dataset_cli snapshot`;
- category verifier train with required evaluation: `category_verifier.train_cli`;
- Patron review labeling CLI: `patron.label_cli`;
- Patron train from a frozen dataset: `patron.train_cli`;
- model artifact inspection and current-version management.

Reusable code belongs in `packages/stroyhub/ml`. Runtime artifacts belong in
`.var/ml`, not in git and not in the product database.

Run the first labeling command locally with:

```bash
uv run python -m apps.ml.category_verifier.label_cli
```

Useful options:

- `--source`: restrict products to one source.
- `--limit`: stop after saving this many labels.
- `--labels-path`: write to a custom JSONL file instead of
  `.var/ml/category_verifier/labels.jsonl`.
- `--labeled-by`: set the label author stored in JSONL.

Check whether enough new labels exist for training with:

```bash
uv run python -m apps.ml.category_verifier.dataset_cli status
```

Create the next frozen dataset snapshot with:

```bash
uv run python -m apps.ml.category_verifier.dataset_cli snapshot
```

Snapshots are stored under `.var/ml/category_verifier/datasets/` as
`v001.jsonl`, `v002.jsonl`, and matching `*.meta.json` files.

Train the verifier on the current live labels with:

```bash
uv run python -m apps.ml.category_verifier.train_cli
```

Training refuses to run until there are at least 50 newly labeled products since
the latest snapshot. Use `--force` only for smoke checks or early experiments.
The command creates the next dataset snapshot, trains a small token baseline,
runs held-out evaluation, saves `.var/ml/category_verifier/models/vNNN/`, writes
`reports/errors/vNNN.jsonl`, and updates `models/current` after success.

## Patron Review

Patron-generated uncertain catalog suitability decisions should be written to:

```text
.var/ml/patron/review.jsonl
```

Run manual review with:

```bash
uv run python -m apps.ml.patron.label_cli
```

The CLI shows one source product at a time, including `price_text` when present
so source labels such as `от ...` are preserved. Manual labels are recorded in
`.var/ml/patron/human_labels.jsonl`.

`.var/ml/patron/labels.jsonl` is the full bulk label ledger with source product
ids. Keep it when appending future bulk labels; use `human_labels.jsonl` for
manual review sessions.

Controls:

- `1`: product;
- `2`: not product;
- `s`: skip;
- `u`: undo;
- `q`: quit.

## Patron Training

Frozen datasets for Patron are stored with model artifacts:

```text
.var/ml/patron/models/v3/dataset.jsonl
```

Build the next dataset snapshot from the current database plus label overlays:

```bash
uv run python -m apps.ml.patron.dataset_cli --model-dir .var/ml/patron/models/v3
```

The builder exports one current source product per row, omits database/source
ids from the frozen dataset, and applies labels by priority:

- admin Patron review in `operator_decisions` and CLI human labels from
  `.var/ml/patron/human_labels.jsonl`;
- bulk labels from `.var/ml/patron/labels.jsonl`;
- current StroyHub policy/DB state.

`skip` decisions are not training labels, and `undo` removes the undone review
decision from the overlay. Re-running the command rewrites the snapshot, so
review rows are idempotent rather than appended repeatedly.

Legacy not-product classifier v0/v1 artifacts are archived under:

```text
.var/ml/patron/archive/not_product_classifier/
```

Train Patron v3 with:

```bash
uv run python -m apps.ml.patron.train_cli
```

The command trains a lightweight TF-IDF + SGD logistic-regression model without
adding external ML dependencies, evaluates on a stratified held-out split, saves
`model.joblib`, `metadata.json`, and `eval_errors.jsonl` under the selected
model directory, and updates `.var/ml/patron/models/current`. Synthetic
not-product support data can be passed with `--extra-dataset-path`; synthetic
rows should carry `label_source=synthetic_not_product` and `synthetic=true` so
they stay auditable and train-only.

Runtime uses `.var/ml/patron/models/current` by default. Override it with
`STROYHUB_PATRON_MODEL_DIR` when the model artifacts live outside the repo-local
`.var/` tree.

Before enabling scheduled scrapes after a deploy or on an existing database,
check both the model artifact and catalog eligibility coverage:

```bash
uv run python scripts/check_patron_readiness.py
```

If existing source products still miss `raw.catalog_eligibility`, run:

```bash
uv run python scripts/backfill_product_suitability.py
uv run python scripts/backfill_product_suitability.py --apply --require-complete
```
