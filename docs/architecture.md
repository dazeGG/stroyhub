# Architecture

StroyHub starts as a Python monorepo with thin applications and one reusable domain package.

## Boundaries

- `apps/api` owns HTTP entrypoints and API composition.
- `apps/worker` owns Celery startup and background task registration.
- `packages/stroyhub` owns reusable parsing, catalog, persistence, and scraping logic.
- `infra` owns local infrastructure definitions.
- `docs` owns long-lived decisions and source notes, not task tracking.

The API and worker should depend on `stroyhub`, while `stroyhub` should not depend on either application package.
