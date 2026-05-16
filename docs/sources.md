# Data Sources

## 2GIS

Primary MVP source. Expected to provide most initial product cards.

Known endpoint:

```text
GET https://market-backend.api.2gis.ru/5.0/product/items_by_branch
```

Known query parameters:

- `branch_id`
- `locale=ru_RU`
- `page`
- `page_size`

Known useful fields:

- product title
- price
- description
- category
- photos
- `updated_at`

Known smoke-test branch:

- `70000001007229923`

Notes:

- Unofficial API.
- No known authentication requirement at the time of planning.
- Raw responses should be stored because the response shape may change.
- Parser health should track branch id, page count, item count, failures, and last successful scrape.
- Source timestamps and parser timestamps must be stored separately.

## Unicom Yakutsk

Secondary JSON source.

Known endpoint pattern:

```text
GET https://unicom-ykt.ru/api2/v-catalog-beta/products/{UUID}
```

Known query parameters:

- `shop=uc`
- `page`
- `sort`
- `limit`

Notes:

- Custom JSON API.
- No known authentication or rate limiting at the time of planning.
- Exact category UUID discovery still needs research.
- Raw responses should be stored for replay and schema drift checks.

## Metalltorg

Secondary HTML source.

Notes:

- Bitrix-based site.
- No stable JSON API is known at the time of planning.
- Parsing will likely use HTML extraction and should be treated as brittle.
- CSS selectors and sample pages should be documented before implementation.

## General Source Rules

- Every parser should emit a shared parsed-product structure.
- Every source response item should preserve raw payload data where possible.
- Money should be parsed into decimal values, not floats.
- Units should preserve both raw text and later normalized values.
- Source-specific identifiers should be stored whenever available.
