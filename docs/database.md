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
- The MVP product taxonomy uses two levels:
  - root categories group material families and navigation sections;
  - child categories are the assignable product categories.
- Products, manual overrides, ML labels, and future ML predictions should target
  child/leaf categories only. Root categories should not receive products
  directly.
- The database intentionally keeps the flexible `parent_id` schema instead of
  enforcing the two-level MVP policy, so later taxonomy decisions do not require
  a schema rewrite.
- The initial normalized StroyHub category tree is defined in
  `packages/stroyhub/catalog/taxonomy.py` and can be seeded with
  `uv run python scripts/seed_categories.py`.

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
- `is_not_product`: `boolean`, required, default `false`
- `created_at`: `timestamp with time zone`, required
- `updated_at`: `timestamp with time zone`, required

Category fields:

- `category_raw` stores the source category exactly as received, such as `Строительные смеси` or `Каталог / Стройматериалы / Цемент`.
- `category_id` points to StroyHub's normalized `categories` table.
- For the MVP, `category_id` should point to a child/leaf category, not a root
  grouping category.

Both fields are needed. `category_raw` preserves source context and supports reprocessing/debugging. `category_id` gives stable filtering for API and UI.

Product validity flag:

- `is_not_product` marks source cards that were observed in a product feed but
  should be excluded from product labeling/review workflows because they are
  not real sellable product cards for the catalog.
- Rescraping should preserve `is_not_product` unless a caller explicitly
  provides a new value.
- The flag should not delete source data or price history; it only changes
  downstream selection/review behavior.

Manual category overrides:

- Store reviewer corrections separately in the `category_overrides` table
  instead of mutating source payloads or encoding one-off exceptions in rules.
- When an active override exists for a source product, it should take
  precedence over source category aliases and rule-based categorization.
- `source_products.category_id` can continue to store the current effective
  category for filtering, but the override row is the audit source of truth.
- Rescraping a product should preserve active overrides and reapply them when
  calculating the effective `category_id`.

`category_overrides` table:

- `id`: `bigint` primary key
- `source_product_id`: `bigint`, required reference to `source_products.id`
- `category_id`: `bigint`, required reference to `categories.id`
- `previous_category_id`: `bigint`, nullable reference to `categories.id`
- `reason`: `text`, nullable
- `status`: `text`, required, default `active`
- `created_by`: `text`, nullable
- `created_at`: `timestamp with time zone`, required
- `updated_by`: `text`, nullable
- `updated_at`: `timestamp with time zone`, required
- `deactivated_by`: `text`, nullable
- `deactivated_at`: `timestamp with time zone`, nullable

Status values:

- `active`: override is the current manual category decision.
- `replaced`: override was superseded by a newer manual decision.
- `reverted`: override was intentionally removed and rules/aliases should apply again.

Constraints and indexes:

- Unique partial index: `source_product_id` where `status = 'active'`.
- Index: `category_id`.
- Index: `status`.
- Index: `created_at`.

Audit metadata should be kept even when the actor is a local script rather than
a future admin user. Use stable actor strings such as `local_script`,
`admin:<username>`, or `system:<job-name>`.

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

### `canonical_products`

Stores StroyHub's source-neutral grouped product identity for accepted product
matches.

M10 schema decision:

- The product matching prototype supports exact title matches, token-similarity
  candidates, attribute blockers, and candidate reporting without persistence.
- Based on that prototype, M10 accepts adding canonical product tables as an
  additive matching layer.
- `source_products` remains the source-of-truth table. Matching must not delete,
  rewrite, or collapse source product cards.

Core fields:

- `id`: `bigint` primary key
- `category_id`: `bigint`, nullable reference to `categories.id`
- `title`: `text`, required
- `normalized_title`: `text`, required
- `brand`: `text`, nullable
- `model`: `text`, nullable
- `unit_raw`: `text`, nullable
- `attributes`: `jsonb`, nullable
- `match_status`: `text`, required, default `active`
- `created_at`: `timestamp with time zone`, required
- `updated_at`: `timestamp with time zone`, required

Rules:

- A canonical product should describe the grouped product identity, not a shop
  listing.
- `title` is the StroyHub display title for the group.
- `attributes` stores extracted matching attributes when useful, such as
  dimensions, weight, grade, color, or package data.
- `category_id` may be nullable while candidates are being reviewed.

Constraints and indexes:

- Index: `category_id`
- Index: `normalized_title`
- Optional future index: trigram or full-text index on `normalized_title` after
  real query patterns justify it.

### `product_matches`

Links source product cards to canonical products and records how the match was
created or reviewed.

Core fields:

- `id`: `bigint` primary key
- `canonical_product_id`: `bigint`, required reference to `canonical_products.id`
- `source_product_id`: `bigint`, required reference to `source_products.id`
- `confidence`: `numeric(4, 3)`, required
- `status`: `text`, required
- `method`: `text`, required
- `matched_at`: `timestamp with time zone`, required
- `reviewed_at`: `timestamp with time zone`, nullable
- `reviewed_by`: `text`, nullable
- `reason`: `jsonb`, nullable

Status values:

- `candidate`: generated but not accepted.
- `accepted`: active match.
- `rejected`: reviewed and rejected.
- `superseded`: replaced by a newer match decision.

Method values:

- `exact_title`
- `token_similarity`
- `attribute_rules`
- `manual`
- `embedding`

Rules:

- At most one accepted canonical match should exist for a source product.
- Candidate and rejected rows may be retained for audit and review context.
- `reason` stores explainable matching metadata such as matched normalized title,
  token overlap, missing tokens, ignored tokens, blockers, and source/category
  compatibility.
- Auto-acceptance should be limited to very high-confidence exact or near-exact
  matches. Medium-confidence candidates should remain reviewable.

Constraints and indexes:

- Unique partial index: `source_product_id` where `status = 'accepted'`.
- Index: `canonical_product_id`.
- Index: `source_product_id`.
- Index: `status`, `confidence`.

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

## Out of Scope for M10 Matching Persistence

- Destructive merging or rewriting of `source_products`.
- Embedding/ML similarity as a required matching method.
- Automatic acceptance of medium-confidence candidates.
- Admin UI accept/reject workflows.
- Price normalization or unit conversion across matched products.
- Cross-shop canonical price aggregation in the API.

## Deferred Questions

These questions should not block M1:

- Whether `numeric(12, 2)` is enough for all price formats after real data collection.
- Whether category `path`, `level`, or `sort_order` should be added after category UX requirements are clearer.
- Whether `source_products.normalized_title` needs full-text search indexes or trigram indexes for API search.
- Whether snapshots should eventually be compressed or split into price changes plus product observations.
- Whether status text values should become PostgreSQL enums.
- Whether accepted canonical matches should later power aggregate API responses
  by default or remain a separate opt-in view.
