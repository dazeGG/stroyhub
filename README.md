# StroyHub

StroyHub is a price aggregator for construction materials in Yakutsk. The MVP focuses on collecting source product cards, saving price history, and exposing searchable product data.

## Project Layout

```text
apps/
  api/                  FastAPI entrypoint: apps.api.main
  worker/               Celery worker entrypoint: apps.worker.celery_app
packages/
  stroyhub/             Reusable domain package
docs/                   Architecture and source notes
infra/                  Local infrastructure files
scripts/                Developer and one-off scripts
tests/                  Automated tests
```

The reusable logic lives in `packages/stroyhub`. Applications in `apps/` should stay thin and call into that package.

## Local Setup

Install `uv` first if it is not available:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then sync the project environment:

```bash
uv sync --all-extras
cp .env.example .env
```

This creates a local `.venv` using the Python version pinned in `.python-version`. The virtual environment is not committed; dependency versions are committed in `uv.lock`.

Start local services:

```bash
docker compose up -d
```

If your Docker installation uses the standalone Compose command:

```bash
docker-compose up -d
```

Docker Desktop or another Docker daemon must be running before starting the services.

Run the current smoke test:

```bash
uv run pytest
```

Run the API locally:

```bash
uv run uvicorn apps.api.main:app --reload
```

Run the Celery worker locally:

```bash
uv run celery -A apps.worker.celery_app:celery_app worker --loglevel=info
```

Run Celery Beat in a second terminal to dispatch due shops every day at
`00:00 Asia/Yakutsk`:

```bash
uv run celery -A apps.worker.celery_app:celery_app beat --loglevel=info
```

Before the first local scrape, seed the normalized category tree and the initial
2GIS shop whitelist in one repeatable setup flow:

```bash
uv run python scripts/setup_data_collection.py
```

Preview the setup without writing to the database:

```bash
uv run python scripts/setup_data_collection.py --dry-run
```

Run the initial 2GIS whitelist scrape and persist baseline product data:

```bash
uv run python scripts/scrape_twogis_whitelist.py
```

Run an explicit live 2GIS smoke check for one branch without persisting data:

```bash
uv run python scripts/scrape_twogis_shop.py 70000001007229923 --page-size 50 --max-pages 3
```

Inspect recent scrape runs:

```bash
uv run python scripts/report_scrape_runs.py --source 2gis --days 7
```

Inspect uncategorized products by source shop and raw source category:

```bash
uv run python scripts/report_category_coverage.py --source 2gis
```

Seed the initial 2GIS whitelist into `shops`:

```bash
uv run python scripts/seed_twogis_whitelist.py
```

Seed the normalized StroyHub category tree into `categories`:

```bash
uv run python scripts/seed_categories.py
```

## Tracker

Project tasks are tracked in GitHub Issues and the [StroyHub MVP project](https://github.com/users/dazeGG/projects/1).

## Runbooks

- [Local data collection](docs/local-data-collection.md)
