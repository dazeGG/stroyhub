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

## Tracker

Project tasks are tracked in GitHub Issues and the [StroyHub MVP project](https://github.com/users/dazeGG/projects/1).
