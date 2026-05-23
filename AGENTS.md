# AGENTS.md

This file gives working instructions for coding agents and contributors in this repository. It applies to the whole repo.

## Project Summary

StroyHub is a price aggregator for construction materials in Yakutsk.

The MVP focuses on:

- collecting source product cards;
- storing price history;
- exposing searchable catalog data;
- avoiding early cross-shop canonical product matching until enough real data is collected.

Current primary source:

- 2GIS product API, documented in `docs/sources.md`.

Current secondary sources:

- Unicom Yakutsk JSON API;
- Metalltorg HTML parsing.

## Current Stack

Use the stack already chosen for the MVP:

- Python;
- FastAPI for the API entrypoint;
- Celery for worker entrypoint;
- PostgreSQL;
- Redis;
- SQLAlchemy;
- Alembic;
- `httpx` for HTTP clients;
- `uv` for Python/dependency management.

Do not introduce Go, Rust, Node, Poetry, Pipenv, or another package manager unless a later explicit project decision changes this.

## Repository Layout

Current layout:

```text
apps/
  api/                  Public FastAPI entrypoint: apps.api.main
  admin_api/            Admin/operator FastAPI entrypoint: apps.admin_api.main
  admin/                Vue admin UI
  worker/               Celery worker entrypoint: apps.worker.celery_app
packages/
  stroyhub/             Reusable domain package
docs/                   Architecture, source notes, decisions, database design
infra/                  Local infrastructure files
scripts/                Developer and one-off scripts
tests/                  Automated tests
```

Important boundaries:

- `apps/api` owns the public read-only HTTP entrypoint and API composition.
- `apps/admin_api` owns admin/operator HTTP routes and API composition.
- `apps/admin` owns the Vue admin UI.
- `apps/worker` owns Celery startup and background task registration.
- `packages/stroyhub` owns reusable parsing, catalog, persistence, and scraping logic.
- `docs` stores long-lived project knowledge, not task tracking.
- GitHub Issues and the StroyHub MVP GitHub Project store tasks and task status.

Do not add `stroyhub_api` or `stroyhub_worker` packages. The project intentionally uses direct app modules:

- `apps/api/main.py`
- `apps/admin_api/main.py`
- `apps/worker/celery_app.py`

## Package Boundaries

Inside `packages/stroyhub`:

```text
core/       Configuration, logging, shared errors
db/         Database session and repository helpers
models/     SQLAlchemy models
parsers/    Source-specific extraction code
catalog/    Product, category, price, and normalization services
scraping/   Scrape orchestration and persistence workflow
ml/         Later classification and matching experiments
```

Rules:

- `apps/api`, `apps/admin_api`, and `apps/worker` may import from `stroyhub`.
- `apps/api` and `apps/admin_api` should not import each other's route modules.
- `stroyhub` must not import app modules.
- Parsers should not write to the database directly.
- Parsers should fetch source data and map it into shared parsed records.
- Scraping code should coordinate shop/source selection, parser execution, persistence, and scrape-run metadata.

## Environment

Python is managed with `uv`.

Files:

- `.python-version` pins Python to `3.12`.
- `uv.lock` is committed and pins dependency versions.
- `.venv` is local and must not be committed.
- `.uv-cache` and `.uv-python` are local and must not be committed.

Setup:

```bash
uv sync --all-extras
cp .env.example .env
```

Run tests:

```bash
uv run pytest
```

Run lint:

```bash
uv run ruff check .
```

Run type checks:

```bash
uv run mypy packages/stroyhub apps/api apps/admin_api apps/worker
```

Run the public API:

```bash
uv run uvicorn apps.api.main:app --reload
```

Run the admin API:

```bash
uv run uvicorn apps.admin_api.main:app --port 8001 --reload
```

## Local Services

PostgreSQL and Redis are managed through Docker Compose.

Start services:

```bash
docker compose up -d
```

If the local Docker installation uses standalone Compose:

```bash
docker-compose up -d
```

Check services:

```bash
docker-compose ps
```

Known local ports:

- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

Default connection settings are in `.env.example`.

When using Colima, start Colima first:

```bash
colima start
```

Then run Docker Compose as above.

## Database Design

`docs/database.md` is the source of truth for the current database design.

Initial MVP tables:

- `shops`
- `categories`
- `source_products`
- `price_snapshots`
- `scrape_runs`

Current out-of-scope items for the database design:

- `canonical_products`
- cross-shop product matching
- ML-based categorization
- price normalization per kilogram, square meter, or cubic meter

Do not implement out-of-scope database tables unless the project decision is updated first.

### Categories

Categories are hierarchical.

Rules:

- Use `parent_id`.
- Do not enforce a fixed depth in the schema.
- MVP may use 2-3 levels, but the database should allow more.

Keep source categories and StroyHub categories separate:

- `category_raw`: category as received from the source.
- `category_id`: normalized StroyHub category reference.

### Source Products

Store product cards as source-specific records.

Rules:

- Use `source_products`, not generic `products`, for MVP source cards.
- Preserve raw source payloads where possible.
- Keep `source_updated_at` separate from StroyHub parsing timestamps.
- Store `normalized_title` and `fingerprint` for fallback matching.

Matching order:

1. If `source_product_id` exists, match by `source`, `shop_id`, `source_product_id`.
2. If `source_product_id` is missing, match by `source`, `shop_id`, `fingerprint`.
3. Fingerprint matching is best-effort and may create duplicates when source titles change.

Do not implement cross-shop canonical matching in M1.

### Price Snapshots

`price_snapshots` are observations, not only price-change events.

Rules:

- Write one snapshot for every successful product observation during scraping.
- Do not write only when the price changes.
- Use decimal types for money, not floating-point types.
- Store `source_updated_at` separately from `parsed_at`.

## Source Data Rules

See `docs/sources.md` before changing or adding parsers.

General rules:

- Every parser should emit a shared parsed-product structure.
- Every source response item should preserve raw payload data where possible.
- Money should be parsed into decimal values, not floats.
- Units should preserve raw text and later normalized values.
- Source-specific identifiers should be stored whenever available.
- Parser health should track item counts, page counts, failures, and last successful scrape.

2GIS notes:

- Primary MVP source.
- API is unofficial.
- No known authentication requirement at the time of planning.
- Known smoke-test branch: `70000001007229923`.

Unicom notes:

- Secondary JSON source.
- Category UUID discovery still needs research.

Metalltorg notes:

- Secondary HTML source.
- Treat selectors as brittle.
- Document sample pages and selectors before implementation.

## Documentation

Keep long-lived project decisions in repo docs.

Use:

- `docs/architecture.md` for architecture and package boundaries.
- `docs/decisions.md` for project decisions and consequences.
- `docs/sources.md` for source API/parsing assumptions.
- `docs/database.md` for database design.

Use GitHub Issues for task status, backlog, acceptance criteria, and implementation notes.

If an issue discussion creates a lasting architectural or data-model decision, update the appropriate `docs/*.md` file as part of the work.

## Agent Memory

When `agentmemory` is available, use it proactively to save durable working context that should carry across sessions.

Save concise notes for:

- user preferences about workflow, communication style, and tool usage;
- recurring implementation patterns and repository conventions discovered while working;
- lasting architecture, data-model, or source-integration decisions;
- non-obvious bugs, fixes, and verification lessons that may help future work.

Do not save secrets, credentials, `.env` values, temporary scratch details, or short-lived task status. Keep GitHub Issues and the StroyHub MVP GitHub Project as the source of truth for backlog and task status. Keep repo docs as the source of truth for long-lived project decisions, and use memory as a cross-session reminder to consult or update those docs.

## GitHub Tracker

Tasks are tracked in GitHub Issues and the StroyHub MVP GitHub Project.

Use GitHub Issues, milestones, and the StroyHub MVP GitHub Project as the source of truth for current milestone status, task priority, backlog, acceptance criteria, and implementation notes.

For each implementation task:

1. Inspect the issue before editing.
2. Move the Project item to `In Progress` when work starts.
3. Keep comments concise but include what changed and how it was verified.
4. Move the Project item to `Done` and close the issue when acceptance criteria are met.

Do not create duplicate issues when an existing issue already covers the work.

## Git Workflow

Use a lightweight trunk-based workflow.

Current agreed approach:

- `main` should stay working.
- Small setup/docs changes may go directly to `main`.
- Larger implementation tasks should use issue-based feature branches.

Branch naming examples:

```text
feature/4-db-schema
feature/6-alembic-models
feature/7-twogis-client
docs/4-database-design
infra/3-docker-compose
fix/<issue-number>-short-name
```

Do not add a `develop` branch or classic Git Flow unless a later explicit project decision changes this.

After a PR is accepted and the remote branch is deleted, clean up the matching local branch automatically when it is safe:

- confirm the branch upstream is gone;
- confirm the branch's changes are already present in `main` or otherwise accepted, for example with `git cherry main <branch>`;
- delete the local branch when the check is clean;
- do not delete branches with unaccepted or unclear local-only work.

## Commit Messages

Use Conventional Commits for all new commits.

Format:

```text
<type>(optional-scope): <description>
```

Common types:

- `feat`: new feature or capability
- `fix`: bug fix
- `docs`: documentation-only change
- `chore`: maintenance that does not change runtime behavior
- `refactor`: code change that does not add a feature or fix a bug
- `test`: tests only
- `build`: dependency, packaging, or build changes
- `ci`: CI workflow changes
- `perf`: performance improvement

Examples:

```text
docs: add initial database design
infra: add docker compose services
chore: add uv managed environment
feat(db): add shop model
fix(parser): handle missing source product id
test(db): cover source product upsert
```

Prefer concise messages that describe the user-visible or project-visible change. If a commit completes an issue, mention the issue in the body or closing comment.

## Testing Approach

Use a pragmatic TDD style for implementation work.

This does not mean writing a test before every line of code. It means defining the expected behavior before implementing risky or contract-heavy logic, especially where regressions would be expensive or source data is brittle.

Prefer tests-first for:

- parsers and source-specific extraction;
- parsed-product normalization;
- money, date, unit, title, and fingerprint normalization;
- repository upsert and persistence workflows;
- scrape orchestration logic;
- pagination and completeness checks;
- API endpoints and response schemas.

For external sources such as 2GIS, use characterization-first testing before locking behavior:

1. Inspect or capture representative real source responses.
2. Store small focused fixtures under `tests/fixtures/` when they are useful.
3. Write tests against the observed response shape.
4. Implement the parser/client behavior.
5. Update fixtures deliberately when the source contract changes.

Do not test invented assumptions about unofficial APIs as if they were stable contracts. For 2GIS and other brittle sources, real samples plus focused tests are preferred over broad live-network tests.

Use mocked HTTP clients for normal automated tests. Keep live source checks as explicit smoke/debug flows, not required unit tests or default CI behavior.

## Verification Before Finishing Work

Run relevant checks before finalizing changes.

For most code changes:

```bash
uv run pytest
uv run ruff check .
uv run mypy packages/stroyhub apps/api apps/admin_api apps/worker
```

For Docker Compose changes:

```bash
docker-compose config
docker-compose up -d
docker-compose ps
```

For database changes:

- Ensure Docker services are running.
- Ensure Alembic migrations run against local PostgreSQL.
- Keep schema decisions aligned with `docs/database.md`.

If a check cannot run because local infrastructure is unavailable, document that clearly in the issue and final response.

## Do Not Commit

Do not commit local/runtime artifacts:

- `.env`
- `.venv/`
- `.uv-cache/`
- `.uv-python/`
- `.pytest_cache/`
- `.mypy_cache/`
- `.ruff_cache/`
- `__pycache__/`
- IDE files such as `.idea/` or `.vscode/`

These are already covered by `.gitignore`; keep it that way.

## Current Entry Points

API:

```text
apps.api.main:app
```

Admin API:

```text
apps.admin_api.main:app
```

Worker:

```text
apps.worker.celery_app:celery_app
```

Health endpoint:

```text
GET /health
```
