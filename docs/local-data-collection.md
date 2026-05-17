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

Seed normalized categories and the initial 2GIS shop whitelist:

```bash
uv run python scripts/setup_data_collection.py
```

Preview the same flow without writing to the database:

```bash
uv run python scripts/setup_data_collection.py --dry-run
```

The setup flow runs:

1. `scripts/seed_categories.py`
2. `scripts/seed_twogis_whitelist.py`

Both flows are idempotent and can be repeated.

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

Run the initial 2GIS whitelist scrape:

```bash
uv run python scripts/scrape_twogis_whitelist.py
```

Expected output includes one `shop scrape summary` per whitelisted shop and a
final `whitelist scrape summary`.

For the 2026-05-17 baseline, the initial run produced:

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

For a one-off worker dispatch from Python/Celery internals, use the existing
`stroyhub.scrape_due_shops` task rather than adding live network calls to tests.

## 7. Inspect Results

Recent scrape runs:

```bash
uv run python scripts/report_scrape_runs.py --source 2gis --days 7
```

Uncategorized product coverage:

```bash
uv run python scripts/report_category_coverage.py --source 2gis
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

### 2GIS live source fails or returns partial data

Symptoms:

- `scrape_status=partial`
- `stop_reason=max_pages_reached`
- request exceptions from the unofficial 2GIS endpoint

Guidance:

- Keep live checks explicit.
- Do not add live calls to default tests.
- Keep very large catalogs such as Юником and Востоктехторг out of the normal
  whitelist until a dedicated large-catalog mode exists. See
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
first baseline audit is recorded in `docs/category-quality.md`.
