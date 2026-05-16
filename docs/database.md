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

- `id`
- `source`
- `source_id`
- `name`
- `address`
- `url`
- `raw`
- `last_scraped_at`
- `next_scrape_at`
- `scrape_status`
- `error_count`
- `created_at`
- `updated_at`

Constraints and indexes:

- Unique: `source`, `source_id`
- Index: `next_scrape_at`
- Index: `scrape_status`

### `categories`

Stores StroyHub's normalized category tree.

Core fields:

- `id`
- `parent_id`
- `slug`
- `name`
- `created_at`
- `updated_at`

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

- `id`
- `shop_id`
- `source`
- `source_product_id`
- `fingerprint`
- `title`
- `normalized_title`
- `description`
- `category_id`
- `category_raw`
- `unit_raw`
- `image_url`
- `source_updated_at`
- `raw`
- `first_seen_at`
- `last_seen_at`
- `is_active`
- `created_at`
- `updated_at`

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

- `id`
- `source_product_id`
- `price`
- `currency`
- `unit_raw`
- `source_updated_at`
- `parsed_at`
- `raw`

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

- `id`
- `shop_id`
- `source`
- `status`
- `started_at`
- `finished_at`
- `items_seen`
- `items_saved`
- `error`
- `raw`

Rules:

- Create one run per scrape attempt.
- Record failures with enough context to debug source/API changes.
- Use this table to understand parser health before relying on scheduled scraping.

Constraints and indexes:

- Index: `shop_id`, `started_at`
- Index: `source`, `started_at`
- Index: `status`

## Out of Scope for M1

- `canonical_products`
- cross-shop product matching
- ML-based categorization
- price normalization per kilogram, square meter, or cubic meter

These will be designed after enough real source data has been collected.
