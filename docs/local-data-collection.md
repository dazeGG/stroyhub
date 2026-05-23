# Local Data Collection Runbook

This runbook describes how to go from an empty local database to useful
StroyHub product data.

## 1. Start Local Services

Start PostgreSQL and Redis:

```bash
docker compose up -d
```

If your Docker installation uses standalone Compose:

```bash
docker-compose up -d
```

Check service health:

```bash
docker-compose ps
```

Expected local ports:

- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

## 2. Prepare the Python Environment

Install dependencies and create `.env`:

```bash
uv sync --all-extras
cp .env.example .env
```

Apply database migrations:

```bash
uv run alembic upgrade head
```

## 3. Seed Local Collection Inputs

Seed normalized categories and official shop sources:

```bash
uv run python scripts/setup_data_collection.py
```

Preview the same flow without writing to the database:

```bash
uv run python scripts/setup_data_collection.py --dry-run
```

The setup flow runs:

1. `scripts/seed_categories.py`
2. `scripts/seed_unicom_source.py`
3. `scripts/seed_metalltorg_source.py`

These seed flows are idempotent and can be repeated.

2GIS shops are no longer auto-approved through the setup script. They should be
loaded through the admin candidate review flow, then approved by an operator.

To configure only the official Unicom source:

```bash
uv run python scripts/seed_unicom_source.py
```

The Unicom seed writes one `shops` row with `source=unicom` and
`source_type=official_api`. Its `raw` config stores the category UUID list,
`limit`, `max_pages`, and sort order used by scheduled collection.

For the full official Unicom catalog, prefer discovering all leaf categories
and running them in one weekly sequential pass:

```bash
uv run python scripts/seed_unicom_source.py \
  --discover-categories \
  --limit 100 \
  --categories-per-run 1000 \
  --scrape-interval 604800
```

As of the 2026-05-23 live scan, Unicom had `518` leaf categories and the full
category pass required about `586` requests including the catalog menu. That is
large but acceptable for a weekly official-source refresh, and simpler than
splitting the catalog across many partial batch runs. Keep smaller
`categories-per-run` values for local smoke checks or temporary rate-limit
mitigation.

To configure only the official Metalltorg HTML source:

```bash
uv run python scripts/seed_metalltorg_source.py
```

The Metalltorg seed writes one `shops` row with `source=metalltorg` and
`source_type=official_html`. The accepted MVP scope is only the parent
`Строительные материалы` section:

```text
https://metalltorg.biz/catalog/stroitelnye_materialy_1/
```

That parent listing aggregates products from its child construction-material
sections, so do not seed both the parent and child URLs in the same run.
Additional Metalltorg sections should be researched separately before they are
added. Collection should stay sequential; product-detail pages are reserved for
incremental category enrichment when products are new or missing high-quality
`category_raw`.

## 4. Run an Explicit Live Smoke Check

Live source checks are intentionally explicit and are not part of default unit
tests.

Run one non-persisted 2GIS branch scrape:

```bash
uv run python scripts/scrape_twogis_shop.py 70000001007229923 --page-size 50 --max-pages 3
```

Expected output includes:

- `total`
- `pages`
- `items`
- `parsed`
- `priced`
- `completeness`
- `stop_reason`

This command should not write products, price snapshots, or scrape runs.

## 5. Persist Baseline Product Data

After 2GIS candidates have been approved into tracked `shops`, scrape due shops
or a specific approved source:

```bash
uv run python scripts/scrape_shop_sources.py due --source 2gis
```

The legacy `scripts/seed_twogis_whitelist.py` and
`scripts/scrape_twogis_whitelist.py` scripts are retained for historical/debug
use, but they are no longer part of the normal empty-database setup flow.

For the 2026-05-17 historical whitelist baseline, the initial run produced:

- `shops_total=6`
- `shops_scraped=6`
- `shops_partial=0`
- `shops_failed=0`
- `source_products_saved=651`
- `price_snapshots_saved=651`

The command can be repeated. Repeated successful runs should upsert existing
`source_products` and append new `price_snapshots`.

## 6. Run Scheduled Collection Locally

Start a Celery worker:

```bash
uv run celery -A apps.worker.celery_app:celery_app worker --loglevel=info
```

Start Celery Beat in another terminal:

```bash
uv run celery -A apps.worker.celery_app:celery_app beat --loglevel=info
```

Beat dispatches due shops every day at `00:00 Asia/Yakutsk`.

The due-shop dispatcher currently supports:

- `2gis` branch scrapes;
- `unicom` official API scrapes from the seeded category UUID config;
- `metalltorg` official HTML scrapes from the seeded category URL config.

For a one-off worker dispatch from Python/Celery internals, use the existing
`stroyhub.scrape_due_shops` task rather than adding live network calls to tests.

Source-aware one-off controls are available through:

```bash
uv run python scripts/scrape_shop_sources.py due --source-type official_api
uv run python scripts/scrape_shop_sources.py due --source 2gis --limit 3
uv run python scripts/scrape_shop_sources.py shop --shop-id 775
uv run python scripts/scrape_shop_sources.py shop --source unicom --source-id unicom-yakutsk
```

By default these commands enqueue `stroyhub.scrape_shop` tasks for a running
Celery worker. Add `--sync` only for an intentional local smoke run in the
current process:

```bash
uv run python scripts/scrape_shop_sources.py shop --shop-id 775 --sync
```

Accepted MVP source types are only `2gis`, `official_api`, and
`official_html`. There is no generic `manual` scrape source: admin/manual work
may manage source metadata, links, status, and locks, but products, prices, and
price snapshots must come from external source records. A source record with
`scrape_status=disabled` is skipped by the worker, so an official source can
stay enabled while a noisy 2GIS fallback record is held out of collection.

Command output is intentionally explicit about source type and partial runs. A
due run prints one `source scrape result` line per selected source record plus a
final `due source scrape summary`; synchronous runs include `status=partial`
when a large catalog hits page limits before the source reports completion.

## 7. Inspect Results

Recent scrape runs:

```bash
uv run python scripts/report_scrape_runs.py --source 2gis --days 7
uv run python scripts/report_scrape_runs.py --source unicom --days 7
uv run python scripts/report_scrape_runs.py --source metalltorg --days 7
```

Uncategorized product coverage:

```bash
uv run python scripts/report_category_coverage.py --source 2gis
uv run python scripts/report_category_coverage.py --source unicom
uv run python scripts/report_category_coverage.py --source metalltorg
```

Product API smoke:

```bash
uv run uvicorn apps.api.main:app --reload
```

Then open:

```text
GET http://127.0.0.1:8000/health
GET http://127.0.0.1:8000/products
```

## 8. Common Failure Modes

### Docker daemon is not running

Symptoms:

- `docker-compose ps` cannot connect to Docker.
- PostgreSQL tests are skipped or database commands fail.

Fix:

```bash
colima start
docker compose up -d
```

or start Docker Desktop, then rerun Compose.

### Database schema is missing or stale

Symptoms:

- Scripts fail with missing table/column errors.

Fix:

```bash
uv run alembic upgrade head
```

### 2GIS or Unicom live source fails or returns partial data

Symptoms:

- `scrape_status=partial`
- `stop_reason=max_pages_reached`
- request exceptions from a source endpoint

Guidance:

- Keep live checks explicit.
- Do not add live calls to default tests.
- Unicom official API collection is sequential by configured category UUID.
- Metalltorg official HTML collection is sequential by configured category URL
  and should be treated as selector-brittle.
- Do not add concurrent source scraping until rate-limit behavior is known.
- Keep very large unknown catalogs such as Востоктехторг out of normal
  scheduled collection until source-specific pacing is documented. See
  `docs/sources.md`.

### Repeated scrapes add many price snapshots

This is expected. `price_snapshots` are observations, so each successful
product observation writes a new snapshot. `source_products` should be upserted
by source product id or fingerprint rather than duplicated.

### Category coverage is incomplete

Run:

```bash
uv run python scripts/report_category_coverage.py --source 2gis
```

Use the output to update category aliases, rules, or follow-up issues. The
first baseline audit is recorded in `docs/category-quality.md`. Use
`docs/category-taxonomy-maintenance.md` for the taxonomy update workflow and
review checklist.
