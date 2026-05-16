# Architecture

StroyHub starts as a Python monorepo with thin applications and one reusable domain package. The MVP goal is to collect source product cards, store price history, and expose searchable catalog data without solving full cross-shop product matching too early.

## Boundaries

- `apps/api` owns the HTTP entrypoint and API composition.
- `apps/worker` owns Celery startup and background task registration.
- `packages/stroyhub` owns reusable parsing, catalog, persistence, and scraping logic.
- `infra` owns local infrastructure definitions.
- `docs` owns long-lived decisions and source notes, not task tracking.

The API and worker are intentionally thin modules, not separate installable packages. They should depend on `stroyhub`, while `stroyhub` should not depend on either application.

## Package Layout

```text
packages/stroyhub/
  core/       Configuration, logging, shared errors.
  db/         Database session and repository helpers.
  models/     SQLAlchemy models.
  parsers/    Source-specific extraction code.
  catalog/    Product, category, price, and normalization services.
  scraping/   Scrape orchestration and persistence workflow.
  ml/         Later classification and matching experiments.
```

`parsers` should not write to the database directly. A parser fetches source data and maps it into a shared parsed-product contract. `scraping` coordinates which shop to scrape, calls the right parser, and persists results through `catalog` and `db`.

## MVP Data Shape

The first stable model should distinguish source product cards from future canonical products:

- `shops`: stores source shop identity, such as a 2GIS branch id or source domain.
- `source_products`: stores product cards as seen in one source and one shop.
- `price_snapshots`: stores append-only price observations over time.
- `categories`: stores the initial category tree and rule-based assignments.

Canonical product matching is intentionally later. The MVP should first collect enough real data to understand naming variance, units, and duplicate patterns.

## Runtime

Development is managed with `uv`:

- `.python-version` pins Python to 3.12.
- `uv.lock` pins dependency versions.
- `.venv` is local and ignored by git.

The API can be run with `uv run uvicorn apps.api.main:app --reload`. The worker will be added once Redis and Celery task wiring are ready.
