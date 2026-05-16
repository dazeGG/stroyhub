# Data Sources

## 2GIS

Primary MVP source.

Known endpoint:

```text
GET https://market-backend.api.2gis.ru/5.0/product/items_by_branch
```

Known query parameters:

- `branch_id`
- `locale=ru_RU`
- `page`
- `page_size`

Notes:

- Unofficial API.
- No known authentication requirement at the time of planning.
- Raw responses should be stored because the response shape may change.
