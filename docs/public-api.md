# Public API Endpoints

This document summarizes the read-only public catalog API for the future MVP
site. Run locally with:

```bash
uv run uvicorn apps.api.main:app --reload
```

Interactive OpenAPI docs are available at `GET /docs`; the raw schema is
available at `GET /openapi.json`.

## Scope

The public API exposes catalog reads only. It does not expose admin review
queues, scrape operations, source candidate workflows, manual override audit
metadata, or mutation endpoints.

## System

### `GET /health`

Returns API process health.

Example response:

```json
{"status": "ok"}
```

## Products

### `GET /products`

Search active source product cards with latest price and shop metadata.

Query params:

- `q`: optional text search against title and normalized title.
- `category`: legacy category id filter.
- `category_id`: category id filter; parent categories include descendants.
- `category_slug`: category slug filter; parent categories include descendants.
- `uncategorized`: optional uncategorized-only filter.
- `shop`: shop id filter.
- `sort`: one of `latest_price`, `-latest_price`, `title`, `-title`, `shop`,
  `-shop`, `last_seen_at`, `-last_seen_at`. Default is `-last_seen_at`.
- `limit`: 1-100, default `50`.
- `offset`: default `0`.

### `GET /products/{product_id}`

Returns one public product card with shop and latest price metadata.

### `GET /products/{product_id}/prices`

Returns ordered price snapshots for one source product. Missing products return
`404`.

## Categories

### `GET /categories`

Returns the normalized category tree with product counts.

### `GET /categories/price-summary`

Returns category-level price summary data.

Query params:

- `source`: optional source filter.
- `shop`: optional shop id filter.

