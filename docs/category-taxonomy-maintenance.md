# Category Taxonomy Maintenance

This runbook keeps category changes deliberate, reviewable, and grounded in
real source data.

## Inputs

Use reports before changing taxonomy code:

```bash
uv run python scripts/report_category_coverage.py --source 2gis
uv run python scripts/report_category_coverage.py --source unicom
uv run python scripts/report_category_coverage.py --source metalltorg
```

For already persisted products, test a categorization change without scraping:

```bash
uv run python scripts/backfill_category_ids.py --source 2gis --dry-run
```

Record important audits in `docs/category-quality.md`, especially groups that
stay unmatched, look noisy, or need product-scope decisions.

## What To Change

Choose the smallest durable change:

- Keep the MVP taxonomy at two levels: root categories group product families,
  and child categories are the only categories that receive products.
- Add a source category alias when a source raw category is narrow and stable,
  for example `Профлист, металлочерепица` to `profiled_sheet`.
- Add or adjust keywords when product titles contain reliable domain terms that
  should work across sources.
- Add a leaf category when products are materially different for filtering,
  review, or future matching, and the existing leaves would be misleading.
- Add a root category only when several related leaf categories need a shared
  parent and no current root fits.
- Do not assign products, manual overrides, ML labels, or future ML predictions
  to root categories. They should target child/leaf categories only.
- Do not add aliases for broad raw categories such as `Материалы` or `Сухие
  смеси` when title-specific rules can produce better categories.
- Do not add categories for obvious non-product/job/service cards. Track those
  separately until exclusion rules or review tooling exists.

## Naming And Slugs

Use stable, English, snake_case slugs:

- Root slugs should describe a material family, for example
  `mixes_aggregates` or `insulation_waterproofing`.
- Leaf slugs should describe filterable product families, for example
  `cement`, `profiled_sheet`, or `vapor_barrier_membranes`.
- Avoid brand names in slugs unless the category is inherently brand-specific.
- Avoid source-specific wording in normalized slugs. Keep source wording in
  aliases or raw category notes.
- Keep display names Russian and user-facing.

Categories live in `packages/stroyhub/catalog/taxonomy.py`. Parent categories
must appear before their children because seed and tests rely on that order.
For the MVP, root categories should not have keywords that make them assignable
product categories; keywords belong on child categories.

## Change Workflow

1. Run `scripts/report_category_coverage.py` and identify the raw category or
   title examples that justify the change.
2. Decide whether the fix is an alias, keyword, or category.
3. Update `packages/stroyhub/catalog/taxonomy.py` or
   `packages/stroyhub/catalog/categorization.py`.
4. Add or update tests in `tests/test_categorization.py`.
5. If a new category was added, ensure seed behavior still works:

```bash
uv run pytest tests/test_categorization.py tests/test_category_seed.py
```

6. Run a dry backfill to inspect impact:

```bash
uv run python scripts/backfill_category_ids.py --source 2gis --dry-run
```

7. If the dry-run looks correct, run the backfill without `--dry-run` in the
   intended environment.
8. Paste the quality report summary into the issue or PR when the change was
   driven by real data.

## Review Checklist

- The change is backed by source examples or a recorded audit.
- The taxonomy still has only root and child levels for MVP use.
- Any assigned category is a child/leaf category, not a root grouping category.
- Existing broad categories did not become less specific by accident.
- Exact aliases do not override better title-led categorization.
- Tests cover the new positive case and any relevant false positive.
- `uv run pytest`, `uv run ruff check .`, and mypy pass for code changes.
