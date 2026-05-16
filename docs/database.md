# Database Design

This document records the initial MVP database design. It is the source of truth for implementing SQLAlchemy models and Alembic migrations in M1.

## Principles

- Store source product cards first; canonical cross-shop product matching comes later.
- Preserve raw source context wherever source data may change or need reprocessing.
- Treat price history as observations over time, not only price-change events.
- Keep parsers out of persistence details; they should emit normalized parsed records.

## Tables

### `shops`

Stores one seller/location as seen by a source.

Core fields:

- `id`: `bigint` primary key
- `source`: `text`, required
- `source_id`: `text`, required
- `name`: `text`, required
- `address`: `text`, nullable
- `url`: `text`, nullable
- `raw`: `jsonb`, nullable
- `last_scraped_at`: `timestamp with time zone`, nullable
- `next_scrape_at`: `timestamp with time zone`, nullable
- `scrape_interval`: `integer`, required, default `86400`
- `scrape_status`: `text`, required
- `error_count`: `integer`, required, default `0`
- `created_at`: `timestamp with time zone`, required
- `updated_at`: `timestamp with time zone`, required

Constraints and indexes:

- Unique: `source`, `source_id`
- Index: `next_scrape_at`
- Index: `scrape_status`

### `categories`

Stores StroyHub's normalized category tree.

Core fields:

- `id`: `bigint` primary key
- `parent_id`: `bigint`, nullable self-reference to `categories.id`
- `slug`: `text`, required
- `name`: `text`, required
- `created_at`: `timestamp with time zone`, required
- `updated_at`: `timestamp with time zone`, required

Rules:

- Categories are hierarchical through `parent_id`.
- The schema must allow any number of nested levels.
- The MVP will likely use 2-3 levels, but the database should not enforce that limit.

Constraints and indexes:

- Unique: `parent_id`, `slug`
- Index: `parent_id`

### `source_products`

Stores product cards as observed in one source and one shop.

Core fields:

- `id`: `bigint` primary key
- `shop_id`: `bigint`, required reference to `shops.id`
- `source`: `text`, required
- `source_product_id`: `text`, nullable
- `fingerprint`: `text`, nullable
- `title`: `text`, required
- `normalized_title`: `text`, required
- `description`: `text`, nullable
- `category_id`: `bigint`, nullable reference to `categories.id`
- `category_raw`: `text`, nullable
- `unit_raw`: `text`, nullable
- `image_url`: `text`, nullable
- `source_updated_at`: `timestamp with time zone`, nullable
- `raw`: `jsonb`, nullable
- `first_seen_at`: `timestamp with time zone`, required
- `last_seen_at`: `timestamp with time zone`, required
- `is_active`: `boolean`, required, default `true`
- `created_at`: `timestamp with time zone`, required
- `updated_at`: `timestamp with time zone`, required

Category fields:

- `category_raw` stores the source category exactly as received, such as `Строительные смеси` or `Каталог / Стройматериалы / Цемент`.
- `category_id` points to StroyHub's normalized `categories` table.

Both fields are needed. `category_raw` preserves source context and supports reprocessing/debugging. `category_id` gives stable filtering for API and UI.

Matching rules:

1. If `source_product_id` exists, match by `source`, `shop_id`, `source_product_id`.
2. If `source_product_id` is missing, build and match by `source`, `shop_id`, `fingerprint`.
3. `fingerprint` is a hash built from normalized stable fields, such as `normalized_title`, `unit_raw`, and source/category hints.
4. Fingerprint matching is best-effort. If a source renames a product, duplicates may appear; cross-shop/canonical matching is intentionally later.

Constraints and indexes:

- Unique partial index: `source`, `shop_id`, `source_product_id` where `source_product_id` is not null
- Unique partial index: `source`, `shop_id`, `fingerprint` where `fingerprint` is not null
- Index: `shop_id`
- Index: `category_id`
- Index: `normalized_title`
- Index: `last_seen_at`

### `price_snapshots`

Stores every successful observed price for a source product.

Core fields:

- `id`: `bigint` primary key
- `source_product_id`: `bigint`, required reference to `source_products.id`
- `price`: `numeric(12, 2)`, nullable
- `currency`: `text`, required, default `RUB`
- `unit_raw`: `text`, nullable
- `source_updated_at`: `timestamp with time zone`, nullable
- `parsed_at`: `timestamp with time zone`, required
- `raw`: `jsonb`, nullable

Rules:

- Write one snapshot for every successful product observation during scraping.
- Do not only write when the price changes.
- A repeated same-price snapshot means the product was seen again at that price.
- This helps distinguish an unchanged price from a product missing from a scrape.

Constraints and indexes:

- Index: `source_product_id`, `parsed_at`
- Index: `parsed_at`
- `price` should be a decimal type, not a floating-point type.

### `scrape_runs`

Stores scrape execution metadata for observability and debugging.

Core fields:

- `id`: `bigint` primary key
- `shop_id`: `bigint`, nullable reference to `shops.id`
- `source`: `text`, required
- `status`: `text`, required
- `started_at`: `timestamp with time zone`, required
- `finished_at`: `timestamp with time zone`, nullable
- `items_seen`: `integer`, required, default `0`
- `items_saved`: `integer`, required, default `0`
- `error`: `text`, nullable
- `raw`: `jsonb`, nullable

Rules:

- Create one run per scrape attempt.
- Record failures with enough context to debug source/API changes.
- Use this table to understand parser health before relying on scheduled scraping.

Constraints and indexes:

- Index: `shop_id`, `started_at`
- Index: `source`, `started_at`
- Index: `status`

## PostgreSQL Type Rules

Use these defaults unless a later decision changes them:

- Primary keys: `bigint` identity columns.
- Foreign keys: `bigint`.
- Source identifiers: `text`, because external IDs may be numeric strings, UUIDs, domains, or opaque values.
- Human text fields: `text`.
- Raw payloads: `jsonb`.
- Money: `numeric(12, 2)` for MVP price values.
- Counters: `integer`.
- Booleans: `boolean`.
- Timestamps: `timestamp with time zone`.
- Currency codes: `text`, default `RUB`.

Use timezone-aware timestamps for both source timestamps and StroyHub timestamps.

Important timestamp meanings:

- `source_updated_at`: timestamp from the source, if available.
- `parsed_at`: when StroyHub observed the product/price.
- `created_at`: when the database row was created.
- `updated_at`: when the database row was last updated.
- `first_seen_at`: first time StroyHub observed a source product.
- `last_seen_at`: latest time StroyHub observed a source product.

## Status Values

Status fields should be implemented as text in the initial migration. PostgreSQL enums can be reconsidered later if status values stabilize.

### `shops.scrape_status`

Initial values:

- `new`: shop is known but has not been scraped yet.
- `scheduled`: shop is queued or due for scraping.
- `success`: latest scrape completed successfully.
- `failed`: latest scrape failed.
- `disabled`: shop should not be scraped.

### `scrape_runs.status`

Initial values:

- `running`: scrape started and has not finished yet.
- `success`: scrape finished successfully.
- `failed`: scrape finished with an error.
- `partial`: scrape finished but not all pages/items were collected.

## Initial Defaults

Use these defaults in the first schema implementation:

- `shops.scrape_status`: `new`
- `shops.scrape_interval`: `86400`
- `shops.error_count`: `0`
- `source_products.is_active`: `true`
- `price_snapshots.currency`: `RUB`
- `scrape_runs.status`: no default; it should be explicitly set by scrape orchestration.
- `scrape_runs.items_seen`: `0`
- `scrape_runs.items_saved`: `0`

`created_at`, `updated_at`, `first_seen_at`, `last_seen_at`, `parsed_at`, and `started_at` should be set by application code or database defaults consistently in the SQLAlchemy/Alembic implementation.

## Out of Scope for M1

- `canonical_products`
- cross-shop product matching
- ML-based categorization
- price normalization per kilogram, square meter, or cubic meter
- separate observation table distinct from `price_snapshots`
- PostgreSQL enum types for statuses

These will be designed after enough real source data has been collected.

## Deferred Questions

These questions should not block M1:

- Whether `numeric(12, 2)` is enough for all price formats after real data collection.
- Whether category `path`, `level`, or `sort_order` should be added after category UX requirements are clearer.
- Whether `source_products.normalized_title` needs full-text search indexes or trigram indexes for API search.
- Whether snapshots should eventually be compressed or split into price changes plus product observations.
- Whether status text values should become PostgreSQL enums.
