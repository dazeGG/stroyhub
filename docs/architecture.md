# Architecture

StroyHub starts as a Python monorepo with thin applications and one reusable domain package. The MVP goal is to collect source product cards, store price history, and expose searchable catalog data without solving full cross-shop product matching too early.

## Boundaries

- `apps/api` owns the HTTP entrypoint and API composition.
- `apps/admin` owns the Vue-based admin/review UI.
- `apps/ml` owns experimental/offline dataset labeling, dataset snapshots,
  training, evaluation, and model artifact management commands. ML is deferred
  from the first MVP release.
- `apps/worker` owns Celery startup and background task registration.
- `packages/stroyhub` owns reusable parsing, catalog, persistence, and scraping logic.
- `infra` owns local infrastructure definitions.
- `docs` owns long-lived decisions and source notes, not task tracking.

The API and worker are intentionally thin Python modules, not separate
installable packages. They should depend on `stroyhub`, while `stroyhub` should
not depend on any application module. The admin UI is a separate frontend app
under `apps/admin`; it should talk to `apps/api` over HTTP instead of importing
Python domain code directly.

The ML workspace is also an application boundary, not a separate package. It
may use `stroyhub` database/session helpers and public ML services from
`packages/stroyhub/ml`, but reusable model loaders, feature builders, and
prediction APIs belong in `packages/stroyhub/ml`.

## Package Layout

```text
packages/stroyhub/
  core/       Configuration, logging, shared errors.
  db/         Database session and repository helpers.
  models/     SQLAlchemy models.
  parsers/    Source-specific extraction code.
  catalog/    Product, category, price, and normalization services.
  scraping/   Scrape orchestration and persistence workflow.
  ml/         Reusable ML feature builders, model loaders, and prediction APIs.
```

`parsers` should not write to the database directly. A parser fetches source data and maps it into a shared parsed-product contract. `scraping` coordinates which shop to scrape, calls the right parser, and persists results through `catalog` and `db`.

## MVP Data Shape

The first stable model should distinguish source product cards from future canonical products. The detailed schema is documented in [database.md](database.md).

- `shops`: stores source shop identity, such as a 2GIS branch id or source domain.
- `source_products`: stores product cards as seen in one source and one shop.
- `price_snapshots`: stores append-only price observations over time.
- `categories`: stores the initial category tree and rule-based assignments.
- `scrape_runs`: stores scrape attempt metadata and parser health signals.

Canonical product matching is intentionally later. The MVP should first collect enough real data to understand naming variance, units, and duplicate patterns.

## Runtime

Development is managed with `uv`:

- `.python-version` pins Python to 3.12.
- `uv.lock` pins dependency versions.
- `.venv` is local and ignored by git.

The full local development stack can be run with `docker compose up -d`. This
starts PostgreSQL, Redis, the API, the admin Vite dev server, and the Celery
worker with beat.

The API can also be run manually with
`uv run uvicorn apps.api.main:app --reload`.

The admin UI can also be run from `apps/admin` with its Vite development server.

The worker can also be run manually with:

```bash
uv run celery -A apps.worker.celery_app:celery_app worker --loglevel=info
```

Celery Beat dispatches due shop scraping every 15 minutes:

```bash
uv run celery -A apps.worker.celery_app:celery_app beat --loglevel=info
```

ML commands are run explicitly through `apps/ml`. They read product data from
PostgreSQL and store ML runtime artifacts under `.var/ml`, which is ignored by
git. These workflows are post-MVP experiments and should not be required by the
first release runtime.
