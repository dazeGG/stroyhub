# Admin UI

M12 adds a dedicated admin/review interface for inspecting StroyHub data quality
and scraper health.

## Location

The admin UI lives in:

```text
apps/admin/
```

It is a separate frontend application. It talks to `apps/admin_api` over HTTP and must
not import Python modules from `packages/stroyhub` directly.

## Starter Stack

- Vue 3 for UI components.
- Vite for development and production builds.
- TypeScript for application code.
- Tailwind CSS for layout, spacing, and custom styling.
- Nuxt UI as the Tailwind-based Vue component library through its Vite plugin.
- Vue Router for admin pages.
- pnpm with Node.js 22.12+ for frontend dependency management.

Nuxt UI is used as a Vue component library. M12 does not adopt Nuxt as the app
framework.

Add Pinia, a charting package, or generated API clients only when an implemented
screen needs them.

## Local Commands

Install dependencies:

```bash
cd apps/admin
pnpm install
```

For the full local development stack, including PostgreSQL, Redis, API, Celery
worker with beat, and the admin dev server, run from the repository root:

```bash
docker compose up -d
```

If your Docker installation uses standalone Compose:

```bash
docker-compose up -d
```

Run the public API from the repository root:

```bash
uv run uvicorn apps.api.main:app --reload
```

Run the admin API from the repository root:

```bash
uv run uvicorn apps.admin_api.main:app --port 8001 --reload
```

Run the admin dev server:

```bash
cd apps/admin
pnpm dev
```

The admin dev server proxies `/api/*` requests to the local admin FastAPI app on
`http://127.0.0.1:8001` by default. In Docker Compose, it uses the internal
`http://admin_api:8001` service URL through `VITE_API_PROXY_TARGET`.

## Initial M12 Jobs

The first admin version should help a human answer these questions without
terminal commands:

- What products have we scraped, from which shop, in which category, and at
  what latest price?
- How has a selected product price changed across scrape observations?
- Which shops or sources are failing, stale, or scraping successfully?
- Which products are uncategorized, questionably categorized, or grouped under
  noisy source categories?
- Which future product-match candidates need human review, if matching
  persistence and API support are ready by then?

## M12 Screens

- `/`: product catalog inspection with search, shop/category filters,
  normalized category, raw category, latest price, last-seen metadata, and
  links into price history.
- `/shops`: shop/source management for M13. It shows real shop identities,
  linked 2GIS/official source records, source priority, scrape status,
  last/next scrape times, error counts, hold/disabled/out-of-scope states, and
  link/unlink controls. It manages metadata only and does not expose manual
  product, price, catalog, or price snapshot editing.
- `/prices`: selected source-product detail plus ordered price snapshots from
  `GET /products/{product_id}/prices`. Repeated same-price observations stay
  visible because snapshots are observations, not only price changes.
- `/scrapes`: scrape health dashboard backed by `GET /shops` and
  `GET /scrapes/health`. It shows shop scrape status, next/last scrape times,
  recent runs, and failed/partial counts.
- `/categories`: category quality review backed by `GET /categories/quality`.
  It groups uncategorized products by source, shop, and `category_raw`, shows
  representative titles, and provides copyable issue-comment text.
- `/matches`: read-only product match candidate review backed by
  `GET /matches/candidates`. It shows side-by-side source product comparisons,
  confidence, method, and reason tokens. Accept/reject actions are intentionally
  deferred.

## Review Workflows

### Product Catalog Inspection

Use `/` when checking whether source cards look sane after scraping or
categorization work.

Review steps:

1. Filter by source shop or normalized category.
2. Search for a known material name from a source sample or issue.
3. Confirm title, shop, raw source category, normalized category, latest price,
   and last seen timestamp.
4. Open price history when a latest price looks wrong or stale.

Create an issue when:

- a source repeatedly produces missing or malformed titles, categories, units,
  or prices;
- a normalized category is clearly wrong for several similar products;
- a source card is duplicated because source IDs or fingerprints are unstable.

Use a quick fix when:

- the problem is a narrow parser field extraction bug with a representative
  fixture;
- a category rule or alias can be updated from a small, obvious pattern.

### Price History

Use `/prices` when checking whether the scraper is collecting observations
properly for one source product.

Review steps:

1. Select a product from the picker or open it from the catalog row.
2. Check the ordered snapshot list.
3. Treat repeated same-price rows as expected; they prove the product was seen
   again.
4. Investigate null prices separately from unchanged prices.

Create an issue when:

- price snapshots stop appearing for an active shop;
- null prices cluster under one source, parser, or raw category;
- prices parse into the wrong unit, currency, or magnitude.

### Scrape Health

Use `/scrapes` before and after running scraper jobs.

Review steps:

1. Filter by source or status.
2. Check failed/partial counts first.
3. Scan shops for stale `last_scraped_at`, overdue `next_scrape_at`, or
   disabled status.
4. Read recent runs for item counts, duration, and error text.

Create an issue when:

- a source or shop has repeated failed/partial runs;
- `items_seen` or `items_saved` drops unexpectedly;
- `next_scrape_at` is missing or clearly wrong for an active shop.

### Enqueue Failure Repair

When an admin action commits shop state but enqueue fails, API endpoints return
`503` and save diagnostic metadata in `shops.raw.enqueue_failed`.

Repair flow:

1. Open `/shops` and identify the affected source shop.
2. Verify `scrape_status` and `next_scrape_at` reflect the intended state
   transition from the original action.
3. Retry the same action (shop retry, candidate approve, or strategy
   materialize) after Redis/Celery connectivity is restored.
4. Confirm a new response contains `status = queued` and `task_id`.
5. Clear or overwrite stale `enqueue_failed` metadata during normal subsequent
   successful operator actions.

Use a quick fix when:

- the issue is a known transient local service problem;
- a seed/schedule value is wrong for one shop and can be corrected directly.

### Category Quality

Use `/categories` to turn uncategorized product groups into taxonomy or rule
work.

Review steps:

1. Filter by source or shop when a scraper/parser change is under review.
2. Sort attention by largest unmatched groups.
3. Read representative titles before changing taxonomy.
4. Use the copied report text in GitHub issues or PR notes.

Create an issue when:

- the group implies a new taxonomy leaf or broader category decision;
- several sources disagree on raw category structure;
- titles are too ambiguous and need product-level examples or manual override
  design.

Use a quick fix when:

- a source category alias maps cleanly to an existing category;
- a title keyword rule covers a narrow, obvious group without harming existing
  tests.

### Match Candidates

Use `/matches` as a read-only review aid for the in-memory matcher. It does not
persist reviewer decisions in M12.

Review steps:

1. Start at high confidence, such as `95%+`.
2. Compare titles, shops, categories, normalized titles, overlap tokens, and
   left/right-only tokens.
3. Record examples of true positives and false positives in issues or PRs.
4. Do not treat a visible candidate as an accepted match until persistence and
   review actions exist.

Create an issue when:

- a false positive needs a new blocker for weight, dimensions, color, grade, or
  packaging;
- true positives are common enough to justify persistence or workflow changes;
- reviewers need accept/reject actions, audit fields, or candidate queues.

Use a quick fix when:

- token aliases or low-value tokens can safely improve obvious examples;
- a blocker already exists conceptually and only needs a focused rule/test.
