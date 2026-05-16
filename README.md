# StroyHub

StroyHub is a price aggregator for construction materials in Yakutsk. The MVP focuses on collecting source product cards, saving price history, and exposing searchable product data.

## Project Layout

```text
apps/
  api/                  FastAPI entrypoint
  worker/               Celery worker entrypoint
packages/
  stroyhub/             Reusable domain package
docs/                   Architecture and source notes
infra/                  Local infrastructure files
scripts/                Developer and one-off scripts
tests/                  Automated tests
```

The reusable logic lives in `packages/stroyhub`. Applications in `apps/` should stay thin and call into that package.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

Run the current smoke test:

```bash
pytest
```

## Tracker

Project tasks are tracked in GitHub Issues and the [StroyHub MVP project](https://github.com/users/dazeGG/projects/1).
