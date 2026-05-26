# Product Matching Research

This document records the M6 research direction for merging similar source
products across shops.

M10 update, 2026-05-18: the pure matching prototype and candidate report are
implemented. The conservative `canonical_products` and `product_matches` schema
is accepted for migration work in issue
[#63](https://github.com/dazeGG/stroyhub/issues/63). The database source of
truth now lives in [database.md](database.md).

M16 update, 2026-05-26: matching is now part of the broader catalog-quality
operations pipeline. The operator workflow should use task states such as
ready to accept, needs review, data problem, and in catalog. The detailed state
model and quality gates live in
[catalog-quality-operations.md](catalog-quality-operations.md).

## Goal

StroyHub currently stores source product cards independently. That is the right
MVP default because source fidelity and price history are more important than
early automatic merging.

The next matching layer should:

- group equivalent source products across shops;
- keep the original source product card unchanged;
- expose reviewable match confidence and reason metadata;
- avoid destructive automatic merges;
- allow later manual corrections.

## Data Sample

The local development database had no persisted source products when this
research was run:

```text
source_products = 0
```

Seed examples below were collected on 2026-05-17 with the existing 2GIS scrape
flow, without persistence:

```bash
uv run python - <<'PY'
from stroyhub.scraping import scrape_twogis_branch
from stroyhub.parsers.common import normalize_title

for branch_id in ["70000001007229923", "7037402698836780", "7037402698774152"]:
    result = scrape_twogis_branch(branch_id=branch_id, page_size=50, max_pages=2)
    for product in result.products[:15]:
        print(product.title, normalize_title(product.title), product.category_raw)
PY
```

Observed examples:

| Shop | Title | Normalized title | Source category |
| --- | --- | --- | --- |
| Евролайн | Сайдинг 3.0 GL Amerika D4 (slim) акрил (АСА) графит (238х3000мм) (22шт. упак) | сайдинг 3.0 gl amerika d4 (slim) акрил (аса) графит (238х3000мм) (22шт. упак) | Сайдинг, фасадные панели |
| Евролайн | Панель фасадный Grand Line крупный камень бежевая (0,995*0,39) 0,39кв.м. | панель фасадный grand line крупный камень бежевая (0,995*0,39) 0,39кв.м. | Сайдинг, фасадные панели |
| Пирамида | Пескобетон М200 30кг | пескобетон м200 30кг | Сухие смеси |
| Пирамида | Клей плиточный КНАУФ-Флизен 25кг | клей плиточный кнауф-флизен 25кг | Сухие смеси |
| Пирамида | Штукатурка гипсовая универсальная КНАУФ-Ротбанд 30кг | штукатурка гипсовая универсальная кнауф-ротбанд 30кг | Сухие смеси |
| Пирамида | Цемент М400 50кг | цемент м400 50кг | Сухие смеси |
| Пирамида | ГРУНТ- ЭМАЛЬ ПО РЖАВЧИНЕ 3 В 1 "H" ЧЕРНАЯ 1,9 КГ | грунт- эмаль по ржавчине 3 в 1 "h" черная 1,9 кг | Лакокрасочные |
| Ондулин | Гипсокартон ГСП-А KNAUF (2500мм*1200мм*9,5мм) | гипсокартон гсп-а knauf (2500мм*1200мм*9,5мм) | Гипсокартон |
| Ондулин | Гипсокартон ГСП-Н2 KNAUF (2500мм*1200мм*9,5мм) Влагостойкий | гипсокартон гсп-н2 knauf (2500мм*1200мм*9,5мм) влагостойкий | Гипсокартон |
| Ондулин | Пленка полиэтиленовая 150 мкр,ширина 1,50м | пленка полиэтиленовая 150 мкр,ширина 1,50м | Теплицы и удлинители для теплиц |

Early observations:

- The current `normalize_title` only casefolds and collapses whitespace. It does
  not normalize dimensions, punctuation, units, brands, color variants, or
  packaging counts.
- Some products are clearly variants rather than identical products, for
  example siding with different colors.
- Exact product equality depends on attributes embedded in text: brand, model,
  dimensions, strength class, weight, color, material, and packaging.
- Source categories help narrow candidates, but cannot decide equality.

## Candidate Approaches

### Exact Normalized Title

Match products when `normalized_title` is identical after source parsing.

Pros:

- Simple and explainable.
- Low false-positive risk.
- Good first dedupe signal inside a curated category.

Cons:

- Misses small naming variations.
- Does not handle reordered words, unit spelling, punctuation, or brand aliases.
- Likely low recall across shops.

Use as a high-confidence signal, not the only strategy.

### Token Similarity

Normalize titles into tokens, remove low-value words, normalize units and
numbers, then compare token sets with Jaccard or weighted overlap.

Pros:

- Handles word order and punctuation.
- Easy to debug by showing overlapping and missing tokens.
- Works before ML training data exists.

Cons:

- Can merge variants if color, dimensions, or strength class are not weighted
  strongly enough.
- Needs domain-specific stopwords, unit parsing, and protected tokens.

Recommended as the first candidate generation strategy.

### Attribute-Aware Rules

Extract structured attributes from title/category text before matching:

- brand: `KNAUF`, `Grand Line`, `Геркулес`;
- model/series: `Ротбанд`, `Флизен`, `Amerika D4`;
- dimensions: `2500мм*1200мм*9,5мм`, `238х3000мм`;
- weight/volume: `25кг`, `30кг`, `50кг`, `10л`;
- class/grade: `М400`, `М500`, `М200`;
- color/material: `белый`, `графит`, `акрил`, `влагостойкий`.

Pros:

- Reduces dangerous false positives.
- Produces good review metadata.
- Helps future unit normalization.

Cons:

- Requires iterative domain rules.
- Extraction will be imperfect for messy source titles.

Recommended for blocking and confidence adjustment.

### Embeddings / ML Similarity

Use text embeddings or another ML model to find similar product titles.

Pros:

- Higher recall for semantically similar names.
- Useful once enough reviewed matches exist.

Cons:

- Harder to explain.
- Risky without reviewed positive/negative examples.
- Operationally heavier than M6 needs.

Defer until reviewed matches exist.

## Recommended Strategy

Use a conservative two-stage strategy:

1. Apply the source-product eligibility gate before candidate generation.
   Products marked `is_not_product`, `raw.catalog_eligibility.status =
   "ineligible"`, or `raw.catalog_eligibility.status = "needs_review"` should
   not enter automatic canonical matching.
2. Generate candidates inside the same normalized category, or inside a narrow
   source category cluster when `category_id` is missing.
3. Score candidates with exact-title, token overlap, and extracted attribute
   agreement.
4. Auto-link only very high-confidence exact or near-exact matches.
5. Store medium-confidence candidates for manual review.
6. Never delete or rewrite `source_products`; link them to canonical products
   through a separate match table.

2GIS needs a stricter gate than official shop sources. Broad cards with
non-exact prices, such as `Гвозди` with `от 2 ₽`, should remain saved as source
observations but must not become normalized/canonical products.

Suggested confidence bands:

- `0.95-1.00`: auto-accepted exact or near-exact match.
- `0.75-0.94`: candidate for review.
- `<0.75`: keep unlinked unless manually selected.

Suggested hard blockers:

- different dimensions;
- different weight/volume package;
- different strength/grade such as `М400` vs `М500`;
- different color for finish materials;
- different source category family.

## Accepted Schema

The original proposed schema below was accepted in M10 after prototype review.
Implementation details and future adjustments should be kept aligned with
[database.md](database.md).

### `canonical_products`

Represents StroyHub's grouped product identity. It should stay source-neutral.

Fields:

- `id`: `bigint` primary key
- `category_id`: nullable FK to `categories.id`
- `title`: canonical display title
- `normalized_title`: normalized canonical title
- `brand`: nullable text
- `model`: nullable text
- `unit_raw`: nullable text
- `attributes`: `jsonb`, nullable
- `match_status`: text, required, default `active`
- `created_at`: timestamp with time zone
- `updated_at`: timestamp with time zone

Indexes:

- `category_id`
- `normalized_title`
- optional future trigram index on `normalized_title`

### `product_matches`

Links one source product to one canonical product and records why the link
exists.

Fields:

- `id`: `bigint` primary key
- `canonical_product_id`: required FK to `canonical_products.id`
- `source_product_id`: required FK to `source_products.id`
- `confidence`: `numeric(4, 3)`, required
- `status`: text, required
- `method`: text, required
- `matched_at`: timestamp with time zone
- `reviewed_at`: timestamp with time zone, nullable
- `reviewed_by`: text, nullable
- `reason`: `jsonb`, nullable

Status values:

- `candidate`: generated but not accepted;
- `accepted`: active match;
- `rejected`: reviewed and rejected;
- `superseded`: replaced by a newer match decision.

Methods:

- `exact_title`
- `token_similarity`
- `attribute_rules`
- `manual`
- `embedding`

Constraints and indexes:

- Unique accepted match per `source_product_id`.
- Index: `canonical_product_id`
- Index: `source_product_id`
- Index: `status`, `confidence`

PostgreSQL sketch:

```sql
create table canonical_products (
  id bigint generated always as identity primary key,
  category_id bigint references categories(id),
  title text not null,
  normalized_title text not null,
  brand text,
  model text,
  unit_raw text,
  attributes jsonb,
  match_status text not null default 'active',
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now()
);

create table product_matches (
  id bigint generated always as identity primary key,
  canonical_product_id bigint not null references canonical_products(id),
  source_product_id bigint not null references source_products(id),
  confidence numeric(4, 3) not null,
  status text not null,
  method text not null,
  matched_at timestamp with time zone not null default now(),
  reviewed_at timestamp with time zone,
  reviewed_by text,
  reason jsonb
);

create unique index uq_product_matches_source_product_accepted
  on product_matches(source_product_id)
  where status = 'accepted';

create index ix_product_matches_canonical_product_id
  on product_matches(canonical_product_id);

create index ix_product_matches_status_confidence
  on product_matches(status, confidence);
```

## M10 Prototype Findings

Implemented findings:

- Exact normalized-title matches are high-confidence candidates inside
  compatible categories.
- Token overlap handles reordered words, punctuation differences, low-value
  tokens, and a small set of word-form aliases.
- Attribute blockers prevent dangerous false positives for different dimensions,
  weights, package counts, grades such as `М400` vs `М500`, and finish colors.
- Candidate reporting can print confidence, method, product context, shared
  tokens, missing tokens, ignored tokens, and category compatibility before
  persistence exists.

Remaining out of scope:

- Embedding similarity before reviewed positive/negative examples exist.
- Destructive source-product merging.
- Automatic acceptance of medium-confidence candidates.
- Admin UI review actions.
