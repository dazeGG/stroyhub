# StroyHub ML Workspace

`apps/ml` is the command workspace for dataset labeling, dataset snapshots,
training, evaluation, reports, and model artifact management.

Planned commands:

- category verifier labeling CLI;
- category verifier dataset status;
- category verifier snapshot/export;
- category verifier train with required evaluation;
- model artifact inspection and current-version management.

Reusable code belongs in `packages/stroyhub/ml`. Runtime artifacts belong in
`.var/ml`, not in git and not in the product database.

Run the first labeling command locally with:

```bash
uv run python -m apps.ml.category_label_cli
```

Useful options:

- `--source`: restrict products to one source.
- `--limit`: stop after saving this many labels.
- `--labels-path`: write to a custom JSONL file instead of
  `.var/ml/category_verifier/labels.jsonl`.
- `--labeled-by`: set the label author stored in JSONL.
