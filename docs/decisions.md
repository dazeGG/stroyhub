# Decisions

## 2026-05-16: Start the MVP in Python

Context:
StroyHub is data-heavy: unstable source APIs, HTML parsing, product normalization, categorization, and future ML experiments matter more than raw service throughput during the MVP.

Decision:
Build the MVP in Python and keep the codebase structured enough that scraper, API, or worker pieces can be split out later if needed.

Consequences:
Python remains the default language for the first implementation. Go or Rust can be reconsidered after the data model and scraping behavior are proven.

## 2026-05-16: Use a Python Monorepo With Thin Apps

Context:
The API, worker, CLI scripts, and tests all need the same parser, catalog, scraping, and database logic. Putting that logic under the API package would make FastAPI the accidental center of the system.

Decision:
Keep runnable entrypoints in `apps/` and reusable logic in `packages/stroyhub`.

Consequences:
`apps/api` and `apps/worker` should stay thin. They may import `stroyhub`, but `stroyhub` should not import app modules.

## 2026-05-16: Do Not Create Separate App Packages Yet

Context:
An earlier layout used `stroyhub_api` and `stroyhub_worker` as installable app packages. That was technically tidy, but heavier than needed for the current project.

Decision:
Use direct modules: `apps/api/main.py` and `apps/worker/celery_app.py`.

Consequences:
The project is easier to scan. If the API or worker grows into a separately distributed package later, it can be split deliberately.

## 2026-05-16: Manage Python With uv

Context:
The project should not depend on whatever Python or packages happen to be installed globally on a developer machine.

Decision:
Pin Python with `.python-version`, lock dependencies with `uv.lock`, and create the local virtual environment with `uv sync --all-extras`.

Consequences:
`.venv` is local and ignored. `uv.lock` is committed. Development commands should prefer `uv run ...`.

## 2026-05-16: Store Source Product Cards Before Canonical Products

Context:
Construction material names vary heavily between shops. Trying to perfectly merge products before collecting data would slow down the MVP and likely create brittle assumptions.

Decision:
Model source product cards first. Add canonical products and product matching after enough examples have been collected.

Consequences:
The initial API may show multiple cards that are semantically the same product. That is acceptable for the MVP because price history and source fidelity are the first priority.
