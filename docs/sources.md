# Data Sources

M8 source expansion candidates are tracked in
[`docs/source-candidates.md`](source-candidates.md). Keep this file focused on
sources that have accepted implementation assumptions or parser behavior.
Source fixture conventions are tracked in
[`docs/source-fixtures.md`](source-fixtures.md).

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

Observed response shape for the smoke-test branch on 2026-05-17:

- top-level payload includes `meta` and `result`;
- `result.total` contains the reported product count;
- `result.updated_at` may be a Russian date string such as `Обновлено 13 января 2026`;
- `result.items` contains regular product cards;
- `result.pinned_items` contains promoted/pinned product cards and has the same item shape;
- each item contains `product` and `offer`;
- `product.id`, `product.name`, `product.description`, `product.images`, and
  `product.categories[].label` are useful for `source_products`;
- `offer.price`, `offer.currency`, and `offer.price_value.fixed` are useful for
  `price_snapshots`;
- products without a price may use `offer.price_value.empty`.

Pagination notes:

- collect pages with configurable `page_size`;
- `page_size=50` works for the smoke-test branch; `page_size=100` returned `400`
  during a live check on 2026-05-17;
- stop as complete when the number of regular `items` reaches `result.total`;
- a first page with zero regular items is treated as an empty result;
- an empty page before `result.total` is reached is treated as partial;
- a safety page limit should mark the scrape as partial when it is reached before
  `result.total`.

Known smoke-test branch:

- `70000001007229923`

Validated Yakutsk branches on 2026-05-17:

| Branch ID | Shop | Result |
| --- | --- | --- |
| `70000001007229923` | Евролайн, Курнатовского 86 | `total=106`, `pages=3`, `items=106`, `parsed=106`, `complete` |
| `7037402698774152` | Ондулин, Чернышевского 48 | `total=183`, `pages=4`, `items=183`, `parsed=183`, `complete` |
| `70000001045942794` | Центрстрой, Лермонтова 63 | `total=56`, `pages=2`, `items=56`, `parsed=56`, `complete` |
| `7037402698750719` | Ск-Строй, 50 лет Советской Армии 28 | `total=161`, `pages=4`, `items=161`, `parsed=161`, `complete` |
| `70000001007356408` | Ск-Строй, Покровское шоссе 4 километр 1/2 | `total=170`, `pages=4`, `items=170`, `parsed=170`, `complete` |

No validation failures were observed for these five branches. The branch list is a
research sample, not yet a production scrape schedule.

### 2GIS shop discovery for scheduled scraping

Discovery research for M3 was run on 2026-05-17 for Yakutsk construction-material
shops.

Discovery paths checked:

- Official Catalog API: `GET https://catalog.api.2gis.com/3.0/items`.
- Query shape: `q=стройматериалы`, `type=branch`, `location=129.732,62.027`,
  `locale=ru_RU`, paginated by `page` and `page_size`.
- The official endpoint returned `400 Incorrect values of params: 'key'` without
  an API key. Do not wire scheduled scraping to this endpoint unless a 2GIS
  Catalog API key is explicitly configured.
- Browser search pages may show captcha to automated clients. Text-indexed 2GIS
  search pages were usable for candidate discovery, but should be treated as
  research input rather than a stable machine API.

Observed search counts:

- The issue expectation was about `117` website results for `стройматериалы`.
- The indexed page for related query `Строительные материалы крепёж` showed
  `105` places.
- The indexed page for broad query `Строительные материалы` showed `624` places.
- The official API count for exact `стройматериалы` was not observed because the
  endpoint requires an API key.

Validation method:

- Candidate branch IDs were collected from 2GIS text-indexed search and firm
  pages.
- Each branch was validated with the existing `items_by_branch` scrape flow.
- No persistence was used.
- Validation command:

```bash
uv run python scripts/discover_twogis_shops.py --page-size 50 --max-pages 20
```

Classification rules:

- `active`: product endpoint returned at least one parsed product with price.
- `no_prices`: product endpoint completed but returned no priced products.
- `failed`: product endpoint request or parsing failed.
- `irrelevant`: search candidate is not a construction-material shop and should
  not enter the schedule. No candidates in the current validated seed were marked
  irrelevant.

Validated candidates on 2026-05-17:

| Branch ID | Shop | Address | Classification | Total | Pages | Items | Priced | Completeness | Notes |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| `7037402698889811` | Металл Торг | Проспект Михаила Николаева, 1 | `active` | 18 | 1 | 18 | 18 | `complete` | Small catalog; good schedule candidate. |
| `70000001007229923` | Евролайн | Улица Курнатовского, 86 | `active` | 106 | 3 | 106 | 82 | `complete` | Existing smoke branch; good schedule candidate. |
| `7037402698746785` | Юником | Вилюйский тракт 3 километр, 1/4 | `active` | 18214 | 20 | 1000 | 1000 | `partial` | Very large catalog; needs special pagination/rate-limit decision before schedule. |
| `7037402698836780` | Пирамида | Переулок Космачёва, 2 | `active` | 48 | 1 | 48 | 45 | `complete` | Good schedule candidate. |
| `7037402698755240` | Космос | Улица Космонавтов, 23 | `no_prices` | 0 | 1 | 0 | 0 | `empty` | Keep out of initial schedule. |
| `70000001038286835` | ЛидерСтрой | Улица Жорницкого, 50а | `no_prices` | 0 | 1 | 0 | 0 | `empty` | Keep out of initial schedule. |
| `70000001065271367` | СибНорд | Улица Челюскина, 37/7в | `no_prices` | 0 | 1 | 0 | 0 | `empty` | Keep out of initial schedule. |
| `7037402698774152` | Ондулин | Улица Чернышевского, 48 | `active` | 183 | 4 | 183 | 149 | `complete` | Existing validated branch; good schedule candidate. |
| `7037402698745664` | Интехстрой | Улица Леваневского, 3 | `active` | 213 | 5 | 213 | 187 | `complete` | Good schedule candidate. |
| `70000001062470950` | Востоктехторг | Проспект Михаила Николаева, 25/5 | `active` | 18521 | 20 | 1000 | 1000 | `partial` | Very large catalog; needs special pagination/rate-limit decision before schedule. |
| `70000001021201334` | Строительный мир | Улица Чернышевского, 105 | `active` | 83 | 2 | 83 | 71 | `complete` | Good schedule candidate. |

Recommended initial whitelist for scheduled scraping:

- `7037402698889811` — Металл Торг, Проспект Михаила Николаева, 1.
- `70000001007229923` — Евролайн, Улица Курнатовского, 86.
- `7037402698836780` — Пирамида, Переулок Космачёва, 2.
- `7037402698774152` — Ондулин, Улица Чернышевского, 48.
- `7037402698745664` — Интехстрой, Улица Леваневского, 3.
- `70000001021201334` — Строительный мир, Улица Чернышевского, 105.

Hold out of the initial schedule:

- `7037402698746785` — Юником: active, but the product endpoint reports more
  than 18k products and requires a separate completeness/rate-limit decision.
- `70000001062470950` — Востоктехторг: active, but similarly reports more than
  18k products.
- `7037402698755240` — Космос: no product prices observed.
- `70000001038286835` — ЛидерСтрой: no product prices observed.
- `70000001065271367` — СибНорд: no product prices observed.

### Large 2GIS catalog policy

Decision date: 2026-05-17.

Very large 2GIS catalogs must stay out of the scheduled whitelist until the
project has a dedicated large-catalog mode. This applies at least to:

- `7037402698746785` — Юником.
- `70000001062470950` — Востоктехторг.

Fresh measurement on 2026-05-17, using the debug CLI without persistence:

```bash
uv run python scripts/scrape_twogis_shop.py 7037402698746785 --page-size 50 --max-pages 3
uv run python scripts/scrape_twogis_shop.py 70000001062470950 --page-size 50 --max-pages 3
uv run python scripts/scrape_twogis_shop.py 7037402698746785 --page-size 50 --max-pages 20
uv run python scripts/scrape_twogis_shop.py 70000001062470950 --page-size 50 --max-pages 20
```

Observed results:

| Branch ID | Shop | Max pages | Total | Items fetched | Completeness | Stop reason | Wall time |
| --- | --- | ---: | ---: | ---: | --- | --- | ---: |
| `7037402698746785` | Юником | 3 | 18210 | 150 | `partial` | `max_pages_reached` | 3.51s |
| `70000001062470950` | Востоктехторг | 3 | 18521 | 150 | `partial` | `max_pages_reached` | 5.03s |
| `7037402698746785` | Юником | 20 | 18210 | 1000 | `partial` | `max_pages_reached` | 17.07s |
| `70000001062470950` | Востоктехторг | 20 | 18521 | 1000 | `partial` | `max_pages_reached` | 20.24s |

Risks:

- A full scrape at `page_size=50` would require about 365-371 page requests per
  shop before persistence work is counted.
- `page_size=100` previously returned `400`, so the current safe page size is
  still `50`.
- A normal scheduled worker run would either produce long-running partial
  scrapes or generate large request bursts against an unofficial API.
- Persisting repeated partial slices would add many price snapshots while still
  leaving most of the catalog unseen.

Policy:

- Keep the normal whitelist limited to shops that complete within the default
  `page_size=50`, `max_pages=100` flow.
- Keep Юником and Востоктехторг out of scheduled scraping for now.
- Use `page_size=50`, `max_pages=20` only for explicit research/debug checks on
  large catalogs, not for scheduled collection.
- Before adding large catalogs to the whitelist, implement a separate
  large-catalog mode with per-shop pagination caps, resumable cursor/state,
  request pacing/backoff, and reporting that distinguishes partial slices from
  complete shop observations.
- Update `scripts/seed_twogis_whitelist.py` only after that policy is accepted
  and implemented.

Raw category sample collected on 2026-05-17 from the initial whitelist:

- `Сухие смеси`
- `Гипсокартон и комплектующие`
- `Древесно-плитные материалы`
- `Фанера, ОСП`
- `Кровля и фасад`
- `Профлист, металлочерепица`
- `Сайдинг, фасадные панели`
- `Технониколь Водосточная система ПВХ`
- `Гидропароизоляция`
- `Геотекстиль`
- `Утеплители`
- `Пенополистирол`
- `Экструдированный пенополистирол`
- `Пена монтажная`
- `Герметик`
- `Дюбель`
- `Саморезы стеновые`
- `Саморезы кровельные`
- `Окна VEKA ПВХ`
- `Двери печные, каминные`
- `Эмали, лаки,растворители`
- `Краски düfa`

Notes:

- Unofficial API.
- No known authentication requirement at the time of planning.
- Raw responses should be stored because the response shape may change.
- Parser health should track branch id, page count, item count, failures, and last successful scrape.
- Source timestamps and parser timestamps must be stored separately.

## Unicom Yakutsk

Secondary JSON source.

Research date: 2026-05-17.

Base URL:

```text
https://unicom-ykt.ru
```

Catalog menu endpoint:

```text
GET  https://unicom-ykt.ru/api/catalog-menu-2.php
POST https://unicom-ykt.ru/api/catalog-menu-2.php
```

Both methods returned the same JSON payload during research. The response is a
recursive category tree. Useful category fields:

- `id`: site-local numeric category id as a string;
- `parent_id`: site-local parent id as a string;
- `name`: display category name;
- `name_en`: URL/transliteration slug;
- `level`: tree depth as a string;
- `last`: string flag where `1` means leaf category;
- `uuid`: category UUID used by the product endpoint;
- `childs`: nested child categories.

Known endpoint pattern:

```text
GET https://unicom-ykt.ru/api2/v-catalog-beta/products/{UUID}
```

Known query parameters:

- `shop=uc`
- `page`
- `sort`
- `limit`

Observed product response fields:

- top-level metadata: `from_cache`, `promo`, `stocks`, `filters`, `pages`,
  `productsCount`, `minPrice`, `maxPrice`, `from`, `to`, and `uri`;
- product identity: `id`, `uuid`, `parent_uuid`, `code`, `vendor_code`;
- product display fields: `category`, `name`, `name_en`, `brand`;
- price and quantity fields: `price`, `offer_price`, `price_package`,
  `price_unit`, `quantity`;
- boolean-like flags as string values: `sale`, `hit`, `new`, `on_order`;
- additional fields observed: `images`, `created_date`, `pe_id`, `lr_id`,
  `rating`, and `offers`.

Observed pagination behavior:

- `limit` controls products per page and `pages` changes accordingly;
- `productsCount` contains the total product count for categories with products;
- requesting a page beyond `pages` returns an empty `products` list while keeping
  the category metadata;
- parent categories such as `Строительство конструкций`,
  `Сухие строительные смеси`, and `Крепежные изделия` returned no products
  directly, so the scraper should walk leaf categories where `last = "1"`;
- `limit=100` was accepted for small sample categories, but the production
  client should keep the limit configurable until larger categories are tested.

Representative category UUIDs:

| Path | UUID | Notes |
| --- | --- | --- |
| `Строительство конструкций` | `e6b7f2dc3d5511e8af077062b8b53ba3` | Parent; direct product request returned empty results. |
| `Строительство конструкций / Блоки строительные` | `fac247f1ae6111eca255000c29d1f857` | Leaf category. |
| `Строительство конструкций / Древесно-плитные материалы` | `4c087edc38fe11efa2a0000c29d1f857` | Parent with leaf children such as `ОСП`. |
| `Сухие строительные смеси` | `9952fc533c6a11e8af077062b8b53ba3` | Parent; direct product request returned empty results. |
| `Сухие строительные смеси / Цемент` | `d68e4fb83d4d11e8af077062b8b53ba3` | Leaf sample with 2 products. |
| `Сухие строительные смеси / Сухие клеевые смеси` | `a975a5d53d4d11e8af077062b8b53ba3` | Leaf sample with 18 products. |
| `Изоляционные материалы` | `54fedbbf421c11e88b787062b8b53ba3` | Parent. |
| `Кровля и водосток / Профнастил` | `46d377c7807811eaa229000c29d1f857` | Leaf category. |
| `Лакокрасочные материалы / Краски для наружных работ` | `ef6197bd3e1911e886f37062b8b53ba3` | Leaf sample with 11 products. |
| `Металлопрокат / Трубы металлические` | `c7d676b1bbcf11eca256000c29d1f857` | Leaf category. |

Notes:

- Custom JSON API.
- No authentication requirement was observed during research.
- No rate limit response was observed during focused sample checks, but request
  pacing should still be conservative.
- `shop=uc` did not change the sampled cement response, but the `stocks` block
  contains multiple Yakutsk stock locations. Availability semantics need parser
  research before per-shop stock is modeled.
- Product image URL construction is still unknown. The product response exposes
  an `images` count-like field, not a direct image URL in the sampled payload.
- `created_date` may be `null` or a Unix timestamp string. It should not be
  treated as a reliable source update timestamp until validated.
- Raw responses should be stored for replay and schema drift checks.
- Focused fixtures:
  - `tests/fixtures/unicom/catalog-menu-excerpt.json`;
  - `tests/fixtures/unicom/products-cement-page1.json`.

## Metalltorg

Secondary HTML source.

Notes:

- Bitrix-based site.
- No stable JSON API is known at the time of planning.
- The public catalog page on 2026-05-17 exposes top-level groups and child
  categories including `Строительные материалы`, `Лакокрасочные материалы,
  пена, герметики`, `Инструменты, расходные материалы`, `Интерьер и отделка`,
  `Крепеж`, `Окна и двери`, `Отопление, водоснабжение, вентиляция`,
  `Сантехника`, and `Электротовары`.
- Parsing will likely use HTML extraction and should be treated as brittle.
- CSS selectors and sample pages should be documented before implementation.

## General Source Rules

- Every parser should emit a shared parsed-product structure.
- Every source response item should preserve raw payload data where possible.
- Money should be parsed into decimal values, not floats.
- Units should preserve both raw text and later normalized values.
- Source-specific identifiers should be stored whenever available.
