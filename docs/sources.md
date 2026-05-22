# Data Sources

M8 source expansion is complete. Implemented secondary-source details for
Unicom and Metalltorg live in this file; remaining expansion candidates are
tracked in [`docs/source-candidates.md`](source-candidates.md). Keep this file
focused on sources that have accepted implementation assumptions or parser
behavior.
Source fixture conventions are tracked in
[`docs/source-fixtures.md`](source-fixtures.md).

## Source Precedence Policy

Decision date: 2026-05-22.

M13 changes the source strategy from "2GIS first for every shop" to
"official shop catalogs first where they exist." 2GIS remains valuable for
discovery, fallback coverage, and shops without usable official catalogs, but it
should not be treated as the authoritative catalog for a shop that exposes its
own public catalog or API.

Precedence order for MVP shop/source work:

1. Official shop API or structured catalog endpoint.
2. Official shop HTML catalog, when selectors and pagination are understood.
3. 2GIS product endpoint for discovery, fallback coverage, or shops without a
   usable official catalog.
4. Manual/admin decisions for source status, holds, and temporary exclusions.

For the same real-world shop, official source records and 2GIS source records
should remain separate source-specific records. Do not merge or rewrite
`source_products` across sources. M13 should instead define source priority and
shop identity rules so admin and future public-site flows can choose which
source is preferred for display, QA, and scheduling.

When the same shop is available through both an official source and 2GIS:

- prefer the official source for prices, product titles, availability, and raw
  category context;
- keep 2GIS data as fallback or comparison data unless the official source is
  missing prices, stale, unreachable, or narrower than the 2GIS catalog;
- record duplicate/source-overlap decisions in docs or admin metadata instead of
  deleting source records;
- make source preference explicit before exposing merged shop/product views in
  the public MVP site.

Source priority should consider:

- freshness: observed update timestamps, last successful scrape, and scrape
  cadence;
- category quality: narrow official category paths are preferred over broad or
  noisy source categories;
- price availability: priced product cards are preferred over empty catalog
  listings;
- reliability: stable APIs and predictable pagination are preferred over brittle
  HTML or unofficial endpoints;
- catalog completeness: complete official catalogs are preferred over partial
  slices from large 2GIS catalogs.

M13 follow-up work:

- [#186](https://github.com/dazeGG/stroyhub/issues/186): audit Yakutsk shop
  source inventory for official catalogs.
- [#187](https://github.com/dazeGG/stroyhub/issues/187): wire Unicom official
  catalog into scheduled collection.
- [#188](https://github.com/dazeGG/stroyhub/issues/188): wire Metalltorg
  official catalog into scheduled collection.
- [#189](https://github.com/dazeGG/stroyhub/issues/189): research SibNord
  official catalog source contract.
- [#190](https://github.com/dazeGG/stroyhub/issues/190): research
  Vostoktechtorg official catalog source contract.
- [#191](https://github.com/dazeGG/stroyhub/issues/191): design shop identity
  across official sources and 2GIS.
- [#192](https://github.com/dazeGG/stroyhub/issues/192): expose shop/source
  management details in API.
- [#193](https://github.com/dazeGG/stroyhub/issues/193): add admin shop/source
  management view.
- [#194](https://github.com/dazeGG/stroyhub/issues/194): add source-aware
  scrape controls for shops.
- [#195](https://github.com/dazeGG/stroyhub/issues/195): create M13 shop
  readiness checklist.

## Shop Identity Policy

Decision date: 2026-05-22.

The same real-world shop or store location can appear as multiple source records:
for example an official catalog source and a 2GIS branch. StroyHub should keep
those source records separate, because their product cards, categories, prices,
raw payloads, and scrape health are source-specific. However, admin and future
public-site flows also need a stable way to say "these source records describe
the same shop/location."

M13 should introduce an explicit grouping concept rather than relying only on
name/address conventions in the existing `shops` table.

Proposed model:

- `shop_identities`: StroyHub-owned real-world shop/location records.
- `shops`: source-specific shop/source records, optionally linked to a
  `shop_identity_id`.

The source-specific `shops` table remains the scrape target and source fidelity
record. A shop identity is a display/grouping and governance record, not a
replacement for source-specific shops.

Identity rules:

- Link source records only when they represent the same real seller/location or
  an intentionally accepted same-shop grouping.
- Preserve `shops.source` and `shops.source_id` uniqueness.
- Preserve all `source_products` under their original source-specific `shop_id`.
- Do not use shop identity grouping to perform cross-shop product canonical
  matching.
- When identity is uncertain, leave source records ungrouped until reviewed.

Recommended `shop_identities` fields for the M13 schema follow-up:

- `id`: primary key.
- `display_name`: StroyHub-facing shop/location name.
- `address`: normalized address, nullable.
- `website_url`: preferred official website/catalog URL, nullable.
- `preferred_source`: source slug to prefer for product display when available,
  nullable.
- `status`: `active`, `hold`, `disabled`, or `out_of_scope`.
- `notes`: reviewer/operator notes, nullable.
- timestamps.

Source priority inside a shop identity:

1. Prefer an official source with recent successful scrapes, prices, and usable
   category paths.
2. Use 2GIS as fallback/comparison data when the official source is stale,
   missing prices, unreachable, or incomplete for the category being inspected.
3. Let admin metadata override the default priority when a source is known to be
   temporarily broken or intentionally held.

Admin display rules:

- Show the shop identity as the human-facing shop row where grouping exists.
- Show linked source records underneath it with source, source id, scrape status,
  last/next scrape time, and whether the source is preferred or fallback.
- Show ungrouped source records separately so operators can decide whether to
  link, hold, disable, or leave them as standalone shops.

Public MVP site rules:

- Prefer `shop_identities.display_name` for shop display when present.
- Prefer products/prices from the identity's preferred official source when the
  data is fresh enough.
- Avoid showing merged product claims across sources until canonical product
  matching is explicitly implemented and reviewed.

Required follow-up work:

- [#198](https://github.com/dazeGG/stroyhub/issues/198): add shop identity
  grouping schema.
- [#192](https://github.com/dazeGG/stroyhub/issues/192): expose shop/source
  management details in API.
- [#193](https://github.com/dazeGG/stroyhub/issues/193): add admin shop/source
  management view.
- [#195](https://github.com/dazeGG/stroyhub/issues/195): create M13 shop
  readiness checklist.

## 2GIS

Initial MVP bootstrap source. Expected to provide broad early product-card
coverage, but it is not authoritative for shops with usable official catalogs.

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

## SibNord

Accepted official HTML source candidate. Parser implementation is not yet
scheduled for collection.

Research date: 2026-05-22.

Base URL:

```text
https://sibnord.ru
```

Observed strategy:

- Bitrix-powered server-rendered HTML catalog.
- No stable public JSON catalog API was identified during focused research.
- Product listing pages embed Bitrix JavaScript objects such as
  `JCCatalogItem`; product detail pages embed `JCCatalogElement` and schema.org
  offer metadata.
- `sitemap-iblock-3.xml` exposed 12,665 catalog URLs during research: 405
  section URLs and 12,260 product URLs.

Representative pages:

| Page | URL | Observed notes |
| --- | --- | --- |
| Catalog root | `https://sibnord.ru/catalog/` | Category navigation page. |
| Cement/peskobeton category | `https://sibnord.ru/catalog/stroitelstvo_konstruktsiy/sukhie_smesi/tsement_peskobeton/` | Product listing with priced cards and availability text. |
| Large drill/bits category | `https://sibnord.ru/catalog/instrument_/raskhodnye_materialy_dlya_ruchnogo_i_elektroinstrumenta/bury_sverla_koronki/` | 40 products on page 1; Bitrix pagination reported 12 pages. |
| Cement product | `https://sibnord.ru/catalog/stroitelstvo_konstruktsiy/sukhie_smesi/tsement_peskobeton/63008/` | Product detail page for source product id `63008`, code `УТ-8435`, price `500` RUB. |

Observed listing selectors and signals:

| Field | Selector or extraction hint |
| --- | --- |
| Product card | `div.product-card` inside `div[data-entity="item"]` |
| Source product id | `PRODUCT.ID` in `JCCatalogItem`, or trailing numeric product URL segment |
| Product detail URL | Product link under the card, or `PRODUCT.DETAIL_PAGE_URL` |
| Title | Product card link text, or `PRODUCT.NAME` |
| Price | `.price` text, or `ITEM_PRICES[0].PRICE` in `JCCatalogItem` |
| Currency | `ITEM_PRICES[0].CURRENCY`, observed as `RUB` |
| Unit | `.measure`, observed as `/ шт.` |
| Availability | `.product-item-quantity`, observed as `Наличие: много` |
| Quantity hint | `MAX_QUANTITY` in `JCCatalogItem` |
| Image | `img[src]`, or `PICT.SRC` in `JCCatalogItem` |
| Category path | Breadcrumb links above the listing/detail content |

Observed detail selectors and signals:

| Field | Selector or extraction hint |
| --- | --- |
| Title | `h1` |
| Source product id | Product URL segment, `JCCatalogElement.PRODUCT.ID` |
| Source article/code | `#bx_*_article`, observed as `Код товара: УТ-8435` |
| Price | `meta[itemprop="price"]`, `.price`, or `ITEM_PRICES[0].PRICE` |
| Currency | `meta[itemprop="priceCurrency"]`, observed as `RUB` |
| Availability | `link[itemprop="availability"]`, plus visible `.product-item-quantity` text |
| Unit | `.measure`, observed as `/ шт.` |
| Description | `[itemprop="description"]` |
| Image | product image element or `JCCatalogElement.PICT.SRC` |

Pagination notes:

- Large category pages returned 40 product cards per page during research.
- Bitrix infinite scroll loads the same category URL with `?PAGEN_1=N`.
- `https://sibnord.ru/robots.txt` disallows `/*PAGEN`, so scheduled broad
  pagination must not be enabled without an explicit policy decision.
- A future parser can start with focused fixture-driven HTML extraction and
  conservative configured category/product URLs. Full-site crawling should be
  deferred until pacing, robots policy, and sitemap-vs-pagination behavior are
  reviewed.

Source precedence:

- SibNord official catalog should supersede 2GIS for SibNord product prices,
  titles, availability, images, and category context once parser health is
  accepted.
- 2GIS should remain a fallback/comparison source because the observed 2GIS
  candidate had no priced products, while the official catalog exposes priced
  cards and detail pages.

Focused fixtures:

- `tests/fixtures/sibnord/category-tsement-peskobeton-page1.html`;
- `tests/fixtures/sibnord/product-63008.html`.

Implementation follow-up:

- [#203](https://github.com/dazeGG/stroyhub/issues/203): implement SibNord
  official HTML parser.

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
- Scheduled M13 collection uses the official API as `source=unicom` with
  `source_type=official_api`, seeded by `scripts/seed_unicom_source.py`.
- The seeded collection config stores explicit leaf category UUIDs in
  `shops.raw.category_uuids`; it does not yet auto-walk the full catalog menu.
- Worker collection processes configured categories sequentially, with no
  concurrent requests. Default request options are `limit=50`, `sort=popular`,
  and `max_pages=100`.
- A category that reaches `max_pages` records a `partial` scrape run; a source
  exception records a failed Unicom scrape run and marks the shop failed.
- `shop=uc` did not change the sampled cement response, but the `stocks` block
  contains multiple Yakutsk stock locations. Availability semantics need parser
  research before per-shop stock is modeled.
- Product image URL construction is still unknown. The product response exposes
  an `images` count-like field, not a direct image URL in the sampled payload.
- `created_date` may be `null` or a Unix timestamp string. The initial parser
  maps it to `ParsedProduct.source_updated_at` because it is the only observed
  product-level source timestamp, but it may represent product creation rather
  than the latest source update. Do not use it as a freshness guarantee until
  validated.
- Raw responses should be stored for replay and schema drift checks.
- Focused fixtures:
  - `tests/fixtures/unicom/catalog-menu-excerpt.json`;
  - `tests/fixtures/unicom/products-cement-page1.json`.

## Metalltorg

Secondary HTML source.

Research date: 2026-05-17.

Base URL:

```text
https://metalltorg.biz
```

Sample pages:

| Page | URL | Observed notes |
| --- | --- | --- |
| Catalog root | `https://metalltorg.biz/catalog/` | Category navigation page. |
| Construction materials category | `https://metalltorg.biz/catalog/stroitelnye_materialy_1/` | Product listing page, 20 product cards on page 1, `data-all_count="1185"`, pagination to `?PAGEN_1=60`. |
| Gypsum board category | `https://metalltorg.biz/catalog/stroitelnye_materialy_1/gipsokarton_i_komplektuyushchie/` | Product listing page with 20 product cards and pagination. |
| Brick category | `https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/` | Product listing page with 1 product card and no multi-page pagination. |
| Brick product | `https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/120420/` | Product detail page for article `24407`. |

Scheduled M13 collection:

- Source identity: `source=metalltorg`, `source_type=official_html`,
  `source_id=metalltorg-yakutsk`.
- Seed command: `uv run python scripts/seed_metalltorg_source.py`.
- Default category URL config is intentionally small:
  `https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/`.
- Default pacing is sequential pages/categories, no concurrent requests,
  `timeout=20.0`, and `max_pages=3`.
- A scrape reaching `max_pages` or page-level fetch failures records a
  `partial` scrape run; an orchestration exception records a failed scrape run
  and marks the shop failed.
- Treat selectors as brittle HTML contracts. Parser fixtures under
  `tests/fixtures/metalltorg/` are the characterization baseline and should be
  updated deliberately when source markup changes.

Observed listing selectors:

| Field | Selector or extraction hint |
| --- | --- |
| Product card | `div.item_block[data-id]` |
| Source product id | `div.item_block[data-id]` |
| Product detail URL | `.item-title a[href]` or `a.thumb[href]` inside the card |
| Title | `.item-title a span` |
| Price | `.price[data-currency][data-value]` |
| Currency | `.price[data-currency]` |
| Unit | `.price_measure`, for example `/шт` |
| Image URL | `img[data-src]`; ignore 1x1 lazy placeholder `src` data URLs |
| Stock text | `.item-stock .value` |
| Article/vendor code | `.article_block[data-value]` or detail `.article__value` |
| Pagination next page | `.module-pagination a[href*="PAGEN_1="]` |
| Total count hint | `.bottom_nav[data-all_count]` |

Observed product detail selectors:

| Field | Selector or extraction hint |
| --- | --- |
| Canonical URL | `link[rel="canonical"]` |
| Title | `h1`, with `<title>` as fallback |
| Description | `meta[name="description"]` |
| Breadcrumb/category path | `.breadcrumbs a` |
| Article/vendor code | `.product-info-headnote__article .article__value` |
| Price/currency/unit | same `.price[data-currency][data-value]` and `.price_measure` pattern as listing pages |
| Availability | `link[itemprop="availability"]` or `.item-stock .value` |
| Image URL | product gallery `img[data-src]` |

Notes:

- Bitrix-based site.
- No stable JSON API is known at the time of planning.
- The public catalog page on 2026-05-17 exposes top-level groups and child
  categories including `Строительные материалы`, `Лакокрасочные материалы,
  пена, герметики`, `Инструменты, расходные материалы`, `Интерьер и отделка`,
  `Крепеж`, `Окна и двери`, `Отопление, водоснабжение, вентиляция`,
  `Сантехника`, and `Электротовары`.
- Parsing will likely use HTML extraction and should be treated as brittle.
- Listing pages include large duplicated UI/header/footer HTML. Parser fixtures
  should use focused fragments around product cards and pagination.
- Lazy image placeholders use `src="data:image/gif..."`; prefer `data-src`.
- Product URLs contain a numeric source id segment such as `120420`, and listing
  cards also expose the same id through `data-id`.
- Price values are available in machine-readable `data-value` attributes; parse
  those before falling back to text.
- Pagination uses `PAGEN_1` query parameters and may also expose a "Показать
  еще" button. Use plain pagination links for the first parser version.
- Failure risks: Bitrix theme class names may change; lazy-loading markup may
  omit images; category pages can include no-image placeholders; some categories
  may have no prices or non-product content; broad categories may span many
  pages and require pacing.
- Focused fixtures:
  - `tests/fixtures/metalltorg/category-kirpich-page1.html`;
  - `tests/fixtures/metalltorg/product-kirpich-120420.html`.

## General Source Rules

- Every parser should emit a shared parsed-product structure.
- Every source response item should preserve raw payload data where possible.
- Money should be parsed into decimal values, not floats.
- Units should preserve both raw text and later normalized values.
- Source-specific identifiers should be stored whenever available.
