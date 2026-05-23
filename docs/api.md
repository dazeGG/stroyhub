# Admin API v2 Endpoints

This document summarizes the admin/operator API surface. The public read-only
API is documented separately in [public-api.md](public-api.md). Run the admin
API locally with:

```bash
uv run uvicorn apps.admin_api.main:app --port 8001 --reload
```

Interactive OpenAPI docs are available at `GET /docs`; the raw schema is
available at `GET /openapi.json`.

Validation notes:

- Invalid enum/status inputs return `422` with FastAPI validation details.
- ID path/query params for admin mutation/read endpoints are validated as
  positive integers.
- Admin-facing actor/reason text fields are trimmed and length-constrained.

## System

### `GET /health`

Returns API process health.

Example response:

```json
{"status": "ok"}
```

## Products

### `GET /products`

Search source product cards with latest price and shop metadata.

Query params:

- `q`: optional text search against title and normalized title.
- `category`: legacy category id filter.
- `category_id`: category id filter; parent categories include descendants.
- `category_slug`: category slug filter; parent categories include descendants.
- `shop`: shop id filter.
- `sort`: one of `latest_price`, `-latest_price`, `title`, `-title`, `shop`,
  `-shop`, `last_seen_at`, `-last_seen_at`. Default is `-last_seen_at`.
- `limit`: 1-100, default `50`.
- `offset`: default `0`.

Example:

```http
GET /products?q=cement&category_slug=cement&sort=latest_price&limit=10
```

Example response:

```json
{
  "items": [
    {
      "id": 42,
      "source": "2gis",
      "source_product_id": "abc",
      "title": "Cement M500",
      "normalized_title": "cement m500",
      "description": null,
      "category_id": 7,
      "category_raw": "Cement",
      "unit_raw": "bag",
      "image_url": null,
      "source_updated_at": null,
      "last_seen_at": "2026-05-17T09:00:00Z",
      "shop": {
        "id": 3,
        "source": "2gis",
        "source_id": "70000001007229923",
        "name": "Build Shop"
      },
      "latest_price": {
        "price": "700.00",
        "currency": "RUB",
        "unit_raw": "bag",
        "source_updated_at": null,
        "parsed_at": "2026-05-17T09:01:00Z"
      }
    }
  ],
  "limit": 10,
  "offset": 0
}
```

### `GET /products/{product_id}/prices`

Returns ordered price snapshots for one source product.

Example response:

```json
{
  "product_id": 42,
  "items": [
    {
      "id": 100,
      "price": "650.00",
      "currency": "RUB",
      "unit_raw": "bag",
      "source_updated_at": null,
      "parsed_at": "2026-05-17T08:01:00Z"
    }
  ]
}
```

Missing products return `404`.

### `PUT /products/{product_id}/category-override`

Sets the active manual category override for one source product.

Idempotency contract:

- Repeating the same payload (`category_id`, `reason`, `actor`, with trimmed text)
  does not create a new override row.
- Changing `category_id` or decision metadata replaces the previous active
  override and preserves history.

### `DELETE /products/{product_id}/category-override`

Reverts the active override and restores the previous category.

## Canonical Products

Canonical products are normalized admin-managed product identities. Creating or
editing a canonical product does not mutate source product cards or create
source-to-canonical matches; decision endpoints are tracked separately.

### `GET /canonical-products`

Lists canonical products.

Query params:

- `q`: optional text search against title and normalized title.
- `category_id`: optional normalized category filter; parent categories include
  descendants.
- `match_status`: optional canonical product status filter.
  Allowed: `active`, `inactive`.
- `limit`: 1-100, default `50`.
- `offset`: default `0`.

Example response:

```json
{
  "items": [
    {
      "id": 1,
      "title": "Цемент М500 50кг",
      "normalized_title": "цемент м500 50кг",
      "category_id": 7,
      "category": {"id": 7, "slug": "cement", "name": "Цемент"},
      "brand": null,
      "model": null,
      "unit_raw": "50кг",
      "attributes": {"weight": {"value": "50", "unit": "kg"}},
      "match_status": "active",
      "created_at": "2026-05-23T09:00:00Z",
      "updated_at": "2026-05-23T09:00:00Z",
      "match_counts": {"accepted": 1, "candidate": 2, "rejected": 0}
    }
  ],
  "limit": 50,
  "offset": 0,
  "total": 1
}
```

### `POST /canonical-products`

Creates a canonical product from explicit admin fields. `normalized_title` is
optional and defaults to normalized `title`.

### `POST /canonical-products/from-source/{source_product_id}`

Creates a canonical product seeded from one source product. Defaults are copied
from the source card: `title`, `category_id`, and `unit_raw`. The source product
is not modified or linked by this endpoint.

### `GET /canonical-products/{canonical_product_id}`

Returns one canonical product with match counts, accepted offer context, and
pending candidate source cards for review.

`accepted_source_products` is the flat list of accepted source cards linked to
the canonical product. `accepted_offer_groups` groups the same accepted cards by
`source` and shop so the admin UI can show store offers directly. Each linked
source card includes its latest observed price snapshot when available, raw unit
and category text, source URL/image when available, `last_seen_at`, and match
confidence.

`candidate_source_products` and `rejected_source_products` list pending and
rejected matches for the same canonical product separately from accepted offers.
Source cards marked ineligible by the 2GIS/source-product eligibility gate are
excluded from offer and candidate context.

### `PATCH /canonical-products/{canonical_product_id}`

Updates editable canonical fields: `title`, `normalized_title`, `category_id`,
`brand`, `model`, `unit_raw`, `attributes`, and `match_status`.
`title`/`normalized_title` are validated as non-blank trimmed strings.

## Product Match Decisions

These endpoints record admin decisions that link source product cards to
canonical products. They preserve source product rows and write audit metadata
to `product_matches.reviewed_at`, `reviewed_by`, and `reason`.

### `POST /product-matches/generate-candidates`

Runs durable candidate generation for eligible unmatched source products. The
endpoint creates `product_matches.status = "candidate"` rows only; it does not
auto-accept matches.

Request:

```json
{
  "source": "2gis",
  "shop_id": null,
  "category_id": 7,
  "min_confidence": 0.75,
  "limit": 100
}
```

`actor` is optional (defaults to `admin`), trimmed, and length-limited.

Example response:

```json
{
  "source_products_considered": 42,
  "reference_products_considered": 18,
  "candidates_seen": 12,
  "candidates_created": 8,
  "candidates_skipped_existing": 4
}
```

### `POST /product-matches/accept`

Accepts a source product into an existing canonical product. If the same
accepted link already exists, the response is idempotent. If the source product
is accepted into a different canonical product, the endpoint returns `409`; use
the supersede endpoint to move it.

Request:

```json
{
  "canonical_product_id": 1,
  "source_product_id": 10,
  "actor": "admin",
  "reason": "looks exact"
}
```

### `POST /product-matches/supersede`

Moves a source product from its current accepted canonical product to another
canonical product. The previous accepted match becomes `superseded`; the new
match becomes `accepted`.

### `POST /product-matches/from-source/{source_product_id}/accept`

Creates a new canonical product from the source product and accepts the source
link in one transaction. This is the main action for an eligible unmatched
source card.

### `POST /product-matches/{match_id}/reject`

Rejects a candidate match and stores reviewer metadata. Non-candidate matches
return `409`.

Example decision response:

```json
{
  "id": 22,
  "canonical_product_id": 1,
  "source_product_id": 10,
  "confidence": "1.000",
  "status": "accepted",
  "method": "manual",
  "matched_at": "2026-05-23T09:10:00Z",
  "reviewed_at": "2026-05-23T09:10:00Z",
  "reviewed_by": "admin",
  "reason": {"action": "accept", "note": "looks exact"}
}
```

## Categories

### `GET /categories`

Returns root normalized categories with nested children. `product_count` is
rolled up from active products in each category subtree.

Example response:

```json
{
  "items": [
    {
      "id": 1,
      "slug": "building_mixes",
      "name": "Building mixes",
      "parent_id": null,
      "product_count": 12,
      "children": []
    }
  ]
}
```

### `GET /categories/price-summary`

Returns active product counts and latest-price aggregates by category.

Query params:

- `source`: optional source filter, for example `2gis`.
- `shop`: optional shop id filter.

`min_price`, `avg_price`, and `max_price` use only non-null latest prices.
`priced_product_count` shows how many products contributed to price aggregates.

Example response:

```json
{
  "items": [
    {
      "category_id": 1,
      "category_slug": "cement",
      "category_name": "Cement",
      "product_count": 3,
      "priced_product_count": 2,
      "min_price": "650.00",
      "avg_price": "675.00",
      "max_price": "700.00"
    }
  ]
}
```

### `GET /categories/quality`

Returns category coverage metrics and uncategorized product groups for review.
Manual category edits are not exposed in M12.

Query params:

- `source`: optional source filter.
- `shop`: optional shop id filter.
- `limit_groups`: 1-100, default `50`.
- `titles_per_group`: 1-10, default `3`.

Example response:

```json
{
  "total_products": 100,
  "categorized_products": 92,
  "uncategorized_products": 8,
  "coverage_pct": "92.00",
  "groups": [
    {
      "source": "2gis",
      "shop_id": 3,
      "shop_name": "Build Shop",
      "shop_source_id": "70000001007229923",
      "category_raw": "Raw Category",
      "count": 4,
      "titles": ["Example product"]
    }
  ]
}
```

## Shops

### `GET /shops`

Lists source-specific shop records with scrape and management metadata. Raw
source payloads are not exposed.

Query params:

- `source`: optional source filter.
- `status`: optional scrape status filter.
- `source_type`: optional source type filter. Accepted MVP source types are
  `2gis`, `official_api`, and `official_html`.
- `identity_id`: optional shop identity id filter.
- `identity`: optional relationship filter, `linked` or `unlinked`.

Example response:

```json
{
  "items": [
    {
      "id": 3,
      "shop_identity_id": 9,
      "identity": {
        "id": 9,
        "display_name": "Build Shop",
        "status": "active",
        "preferred_source": "unicom"
      },
      "source": "2gis",
      "source_id": "70000001007229923",
      "source_type": "2gis",
      "name": "Build Shop",
      "address": "Yakutsk",
      "url": null,
      "scrape_status": "ok",
      "last_scraped_at": "2026-05-17T09:00:00Z",
      "next_scrape_at": "2026-05-18T00:00:00Z",
      "scrape_interval": 86400,
      "error_count": 0,
      "is_preferred_source": false,
      "enqueue_failed": null
    }
  ]
}
```

Shop records are source-specific scrape targets. A linked `identity` groups
multiple source records that describe the same real-world shop/location.

When an immediate scrape enqueue fails after an admin action commits state,
`enqueue_failed` contains `operation`, `failed_at`, and `reason` until the next
successful enqueue clears it.

### `GET /shop-identities`

Lists StroyHub-owned shop identity records for admin grouping and source
governance.

Query params:

- `status`: optional identity status filter: `active`, `hold`, `disabled`, or
  `out_of_scope`.

Example response:

```json
{
  "items": [
    {
      "id": 9,
      "display_name": "Build Shop",
      "address": "Yakutsk",
      "website_url": "https://example.test/catalog/",
      "preferred_source": "unicom",
      "status": "active",
      "notes": "Official catalog first",
      "locked_fields": {"display_name": true},
      "source_count": 2
    }
  ]
}
```

### `POST /shop-identities`

Creates a shop identity. This is admin metadata for grouping source records; it
does not create products, prices, or a manual catalog.

Request body:

- `display_name`: required.
- `address`: optional.
- `website_url`: optional.
- `preferred_source`: optional source slug. `manual` is rejected.
- `status`: optional, defaults to `active`.
- `notes`: optional.
- `locked_fields`: optional object used to mark admin-owned fields that should
  not be overwritten by source refresh logic.

### `PATCH /shop-identities/{identity_id}`

Updates shop identity metadata. Locked fields are preserved by the repository
layer; for example, a locked `display_name` is not overwritten by an update
payload.

### `POST /shop-identities/{identity_id}/sources/{shop_id}`

Links a source-specific shop record to a shop identity. Returns the updated shop
source response shape from `GET /shops`.

### `DELETE /shops/{shop_id}/identity`

Unlinks a source-specific shop record from its current identity. Returns the
updated shop source response shape from `GET /shops`.

### `DELETE /shop-identities/{identity_id}`

Deletes a StroyHub-owned shop identity and detaches any linked source-specific
shop records. Source rows, source products, price snapshots, and scrape history
are preserved.

M13 does not expose endpoints for manual products, manual prices, manual
catalogs, or manual price snapshots. Owner-managed shop behavior should be
modeled later as ownership and management state, not as a generic `manual`
source type.

### `POST /shops/{shop_id}/scrape/retry`

Retries a failed or partial scrape by scheduling the shop source immediately.

Success response includes enqueue metadata:

```json
{
  "shop_id": 3,
  "source": "unicom",
  "source_type": "official_api",
  "status": "queued",
  "task_id": "a3e6a147-76be-4e7f-952e-2f9f9fbf9388",
  "reason": null
}
```

If enqueue fails after the status commit, the endpoint returns `503` and exposes
failure metadata through `GET /shops` as `enqueue_failed`. A later successful
retry clears that field.

## Shop Source Candidates

### `GET /shop-source-candidates`

Lists discovered shop/source candidates that are not yet approved into tracked
`shops` rows. By default approved candidates are hidden.

Query params:

- `status`: optional candidate status filter: `pending`, `stale`, `hidden`,
  `archived`, or `approved`.
- `include_approved`: optional boolean, default `false`.

Example response:

```json
{
  "items": [
    {
      "id": 1,
      "source": "2gis",
      "source_id": "70000001007229923",
      "source_type": "2gis",
      "display_name": "Build Shop",
      "address": "Yakutsk",
      "website_url": null,
      "rubrics": "Стройматериалы; доставка",
      "status": "pending",
      "has_products": true,
      "has_prices": true,
      "has_website": true,
      "product_count": 0,
      "priced_product_count": 0,
      "priority": 100,
      "priority_reason": "есть цены и сайт",
      "last_seen_at": "2026-05-23T00:00:00Z",
      "last_checked_at": "2026-05-23T00:00:00Z",
      "missing_since": null,
      "approved_shop_id": null,
      "official_strategy": null,
      "suggested_identity": {
        "id": 7,
        "display_name": "Build Shop",
        "status": "active",
        "source_count": 1,
        "reason": "name_match"
      },
      "scrape_result": null
    }
  ]
}
```

Priority order:

1. Has both a 2GIS goods/prices signal and a website signal.
2. Has a 2GIS goods/prices signal only.
3. Has a website signal only.
4. Other construction-material shop candidates, marked as no prices found.

### `POST /shop-source-candidates/refresh`

Refreshes the candidate queue from 2GIS search discovery pages using search
filters for goods/prices and website signals. It does not scrape product cards
or resolve real website URLs during refresh. New candidates are added, existing
unapproved candidates are updated, and unapproved candidates missing from the
latest refresh are marked `stale` instead of being deleted. Already approved
`shops` are skipped and stay out of the pending queue.

### `POST /shop-source-candidates/{candidate_id}/approve`

Approves a candidate into tracked data. The endpoint creates a `shops` row for
the 2GIS source, resolves the website URL only when the candidate had a website
signal, marks the candidate `approved`, immediately runs the source scrape, and
returns the updated candidate with `scrape_result`.

Optional JSON body:

```json
{
  "shop_identity_id": 7
}
```

When `shop_identity_id` is provided, the created 2GIS source shop is linked to
that existing `shop_identity`, so the admin can display it as another
address/branch of the same real shop while preserving source-specific scrape
data. When omitted or `null`, the source shop stays unlinked.

The scrape result is included only in the approve response:

```json
{
  "scrape_result": {
    "shop_id": 217,
    "source": "2gis",
    "source_type": "2gis",
    "status": "success",
    "duration_seconds": 1.42,
    "products_seen": 64,
    "products_saved": 64,
    "price_snapshots_saved": 64
  }
}
```

If enqueue fails after approval commit, the endpoint returns `503` and writes
`shops.raw.enqueue_failed` for the approved source shop.

### `POST /shop-source-candidates/official-strategies/{source}/materialize`

Materializes an official source strategy into an operational `shops` record and
optionally enqueues an immediate scrape (`run_scrape=true` by default).

If enqueue fails after materialization commit, the endpoint returns `503` and
writes `shops.raw.enqueue_failed` for the materialized source shop.

## Scrapes

### `GET /scrapes/health`

Returns recent scrape runs and status counts for admin health screens. Scrape
raw payloads are not exposed.

Query params:

- `source`: optional source filter.
- `shop`: optional shop id filter.
- `status`: optional scrape run status filter.
- `limit`: 1-100, default `20`.

Example response:

```json
{
  "status_counts": [
    {"status": "failed", "count": 1},
    {"status": "success", "count": 4}
  ],
  "recent_runs": [
    {
      "id": 12,
      "source": "2gis",
      "shop_id": 3,
      "status": "success",
      "started_at": "2026-05-17T09:00:00Z",
      "finished_at": "2026-05-17T09:01:00Z",
      "items_seen": 100,
      "items_saved": 95,
      "error": null
    }
  ]
}
```

## Product Normalization

### `GET /product-normalization/queue`

Returns the admin review queue for deciding how source product cards become
normalized canonical products. This endpoint is read-only; decision endpoints
are tracked separately.

Queue states:

- `ineligible`: stored source card is blocked from canonical matching.
- `needs_review`: source card is not safe enough for automatic matching.
- `eligible_unmatched`: source card can become a canonical product but has no
  accepted match.
- `candidate_match`: source card has one or more candidate matches.
- `accepted`: source card is linked to a canonical product.

Query params:

- `state`: optional queue state filter.
- `source`: optional source filter.
- `shop`: optional shop id filter.
- `category_id`: optional normalized category filter; parent categories include
  descendants.
- `q`: optional text search against title and normalized title.
- `limit`: 1-100, default `50`.
- `offset`: default `0`.

Example response:

```json
{
  "items": [
    {
      "id": 10,
      "state": "eligible_unmatched",
      "source": "2gis",
      "source_product_id": "123",
      "title": "Цемент М500 50кг",
      "normalized_title": "цемент м500 50кг",
      "category_id": 7,
      "category_slug": "cement",
      "category_name": "Цемент",
      "category_raw": "Сухие смеси",
      "unit_raw": "шт.",
      "image_url": null,
      "last_seen_at": "2026-05-23T09:00:00Z",
      "is_not_product": false,
      "shop": {
        "id": 3,
        "source": "2gis",
        "source_id": "70000001007229923",
        "name": "Build Shop"
      },
      "latest_price": {
        "price": "650.00",
        "currency": "RUB",
        "unit_raw": "шт.",
        "source_updated_at": null,
        "parsed_at": "2026-05-23T09:05:00Z"
      },
      "catalog_eligibility": {
        "status": "eligible",
        "confidence": "1.000",
        "score": 100,
        "reasons": ["exact_price_and_specific_title"]
      },
      "match_summary": {
        "accepted_match_id": null,
        "accepted_canonical_product_id": null,
        "accepted_canonical_title": null,
        "candidate_count": 0,
        "rejected_count": 0
      },
      "candidate_matches": []
    }
  ],
  "limit": 50,
  "offset": 0,
  "total": 1
}
```

For `candidate_match` items, `candidate_matches` contains the persisted
candidate rows with `id`, canonical product title/normalized title/category,
`confidence`, `method`, and `reason` so the admin UI can accept or reject a
specific proposal.

## Matches

### `GET /matches/candidates`

Returns read-only in-memory product match candidates for review. M12 does not
persist accept/reject actions through this endpoint.

Query params:

- `source`: optional source filter.
- `shop`: optional shop id filter.
- `category_id`: optional normalized category filter.
- `category_raw`: optional raw source category filter.
- `min_confidence`: 0-1, default `0.75`.
- `max_confidence`: optional 0-1 upper bound.
- `limit`: 1-100, default `50`.
- `allow_category_mismatch`: default `false`.

Example response:

```json
{
  "products_considered": 2,
  "candidates": [
    {
      "left": {
        "id": 10,
        "source": "2gis",
        "shop_id": 3,
        "shop_name": "Build Shop",
        "shop_source_id": "70000001007229923",
        "title": "Cement M500 50kg",
        "normalized_title": "cement m500 50kg",
        "category_id": 1,
        "category_raw": "Cement"
      },
      "right": {
        "id": 11,
        "source": "2gis",
        "shop_id": 4,
        "shop_name": "Other Shop",
        "shop_source_id": "70000001000000000",
        "title": "Cement M500 50kg",
        "normalized_title": "cement m500 50kg",
        "category_id": 1,
        "category_raw": "Cement"
      },
      "confidence": 1.0,
      "reason": {
        "method": "exact_normalized_title",
        "exact_title": true,
        "matched_normalized_title": "cement m500 50kg",
        "token_overlap": ["50kg", "cement", "m500"],
        "left_only_tokens": [],
        "right_only_tokens": [],
        "ignored_tokens": [],
        "blocked_by": [],
        "token_similarity": 1.0,
        "same_category": true
      }
    }
  ]
}
```
