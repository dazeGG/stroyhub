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

## Shops

### `GET /shops`

Lists known shops with scrape metadata. Raw source payloads are not exposed.

Query params:

- `source`: optional source filter.
- `status`: optional scrape status filter.

Example response:

```json
{
  "items": [
    {
      "id": 3,
      "source": "2gis",
      "source_id": "70000001007229923",
      "name": "Build Shop",
      "address": "Yakutsk",
      "scrape_status": "ok",
      "last_scraped_at": "2026-05-17T09:00:00Z"
    }
  ]
}
```

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
