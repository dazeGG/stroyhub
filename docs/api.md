# API v2 Endpoints

This document summarizes the catalog API surface used by future UI and admin
screens. Run locally with:

```bash
uv run uvicorn apps.api.main:app --reload
```

Interactive OpenAPI docs are available at `GET /docs`; the raw schema is
available at `GET /openapi.json`.

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
      "is_preferred_source": false
    }
  ]
}
```

Shop records are source-specific scrape targets. A linked `identity` groups
multiple source records that describe the same real-world shop/location.

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
      "approved_shop_id": null
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

Approves a candidate into tracked data. The endpoint creates an unlinked `shops`
row for the 2GIS source, resolves the website URL only when the candidate had a
website signal, marks the candidate `approved`, and returns the updated
candidate. A `shop_identity` is created manually later from the admin UI when an
operator wants to group a real shop.

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
