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
.var/ml/patron/models/v2/dataset.jsonl
```

Legacy not-product classifier v0/v1 artifacts are archived under:

```text
.var/ml/patron/archive/not_product_classifier/
```

Train Patron v2 with:

```bash
uv run python -m apps.ml.patron.train_cli
```

The command trains a small rule-guarded, length-normalized token Naive Bayes
baseline without adding external ML dependencies, evaluates on a stratified
held-out split, saves `model.joblib`, `metadata.json`, and `eval_errors.jsonl`
under the selected model directory, and updates
`.var/ml/patron/models/current`.
