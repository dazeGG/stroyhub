# Category Quality Notes

This document records category coverage audits from real persisted source data.

## 2026-05-17 2GIS Baseline Audit

Source data:

- Source: `2gis`.
- Shops: initial 6-shop whitelist.
- Unique active source products: `649`.
- Categorized products: `614`.
- Uncategorized products: `35`.
- Coverage: `94.61%`.

Coverage query:

```sql
select
  count(*) as total,
  count(category_id) as categorized,
  count(*) - count(category_id) as uncategorized,
  round(count(category_id)::numeric * 100 / nullif(count(*), 0), 2) as coverage_pct
from source_products
where source = '2gis' and is_active;
```

Top assigned categories:

| Category | Products |
| --- | ---: |
| `profiled_sheet` | 51 |
| `vapor_barrier_membranes` | 44 |
| `metal_sheets` | 39 |
| `paints_enamels` | 39 |
| `siding_facade_panels` | 35 |
| `drainage_systems` | 35 |
| `polymer_sheets` | 34 |
| `varnishes_wood_protection` | 28 |
| `osb_plywood_dsp` | 27 |
| `geotextiles_fabrics` | 24 |

Uncategorized groups:

| Shop | Raw category | Products | Notes |
| --- | --- | ---: | --- |
| Интехстрой | `Утеплитель межвенцовый` | 8 | False negatives; insulation/natural fiber category coverage needed. |
| Евролайн | `СИП ПАНЕЛИ` | 7 | False negatives; decide existing vs dedicated SIP panel category. |
| Ондулин | `Утеплители` | 4 | False negatives; should map to insulation categories. |
| Строительный мир | `Материалы` | 4 | Generic source category; titles need fallback rules. |
| Евролайн | `Утеплители` | 3 | False negatives; should map to insulation categories. |
| Пирамида | `Мебель` | 3 | Likely outside construction-material MVP scope. |
| Строительный мир | `Работа` | 2 | Non-product/job cards; should not pollute material categories. |
| Строительный мир | `Специального назначения` | 2 | Needs title-based fallback review. |
| Интехстрой | `Штакетник` | 1 | Fence/outdoor material candidate. |
| Интехстрой | `Ящик для пищевых продуктов` | 1 | Likely outside MVP scope. |

Representative false negatives:

- `ISOVER СТАНДАРТ (600*1000*50) 0,24 куб. 4,8 кв.м.(8 плит)`.
- `ТЕХНОБЛОК СТАНДАРТ (1200*600*50)`.
- `Межвенцовый утеплитель ЭКОСТЕН Sintex ПЭ 100мм*20м`.
- `Пакля джутовая 10 кг/тюк`.
- `Панель 1250*2500*109 (0/9) потолочный`.
- `Панель 1250*2500*174 (12/12)`.

Representative noisy/non-product items:

- `Кладовщик`.
- `Продавец-консультант`.
- Bathroom vanity products under `Мебель`.
- `Ящик для пищевых продуктов`.

Potential false positives or coarse matches:

- `Двери печные, каминные` currently maps to `doors`. This is acceptable for
  rough browsing, but may need a dedicated stove/fireplace hardware category if
  that product family matters later.
- Some `Сухие смеси` products map to broad `dry_mixes` even when a more specific
  category exists, for example cement, putty, tile adhesive, and floor mix
  titles. This is usable for M7, but M9 should improve specificity.
- Generic raw categories such as `Материалы` can still map correctly when the
  title has strong signals, for example paint-related titles mapping to
  `paints_enamels`. They also leave several unmatched products, so fallback
  rules should remain title-led rather than raw-category-led.

Follow-up issues:

- [#91](https://github.com/dazeGG/stroyhub/issues/91): Improve insulation category coverage from 2GIS audit.
- [#92](https://github.com/dazeGG/stroyhub/issues/92): Classify SIP panel products from 2GIS audit.
- [#93](https://github.com/dazeGG/stroyhub/issues/93): Handle generic and non-product 2GIS categories from audit.
