# M13 Shop Readiness Checklist

This checklist captures the shop/source readiness state at the end of M13 before
public MVP site work starts.

Snapshot date: 2026-05-22.

Data basis:

- current local database source records and scrape runs;
- `docs/sources.md` 2GIS validation and official-source notes;
- `docs/source-candidates.md` M13 official source audit;
- `docs/category-quality.md` category quality notes.

## Readiness Policy

Use these statuses for public-MVP planning:

- `primary_official`: official shop source should be preferred once it has a
  recent successful scrape with prices.
- `fallback_2gis`: usable 2GIS source record; keep as fallback/comparison data,
  not authoritative when an official source is healthy.
- `hold_disabled`: do not include in normal scheduled collection or public MVP
  display until a listed gap is resolved.
- `out_of_mvp_scope`: useful later, but not required for the construction
  materials MVP.

The MVP must not add a generic `manual` scrape source. Admin work may manage
shop identities, source links, source status, notes, and locked metadata, but
products, prices, and price snapshots should come from external source records:
`2gis`, `official_api`, or `official_html`.

## Source Summary

| Shop/source | MVP readiness | Primary source | Fallback source | Current data snapshot | Known risks / notes | Next action |
| --- | --- | --- | --- | --- | --- | --- |
| Юником | `primary_official` | `unicom`, `official_api`; preferred config discovers all leaf categories and runs a weekly full pass | 2GIS should stay held for normal schedule because it reports about 18k products and only partial slices were validated | M14 smoke on 2026-05-22 used a scoped 6-category config and saved 57 products/snapshots. Follow-up research on 2026-05-23 validated the full official category pass: 518 leaf categories, about 586 requests, and 18139 reported products. | Image URL semantics and stock semantics are still limited | Use official API as preferred source for public MVP; configure full official collection with `limit=100` and no category batching for weekly refreshes |
| Металл Торг | `primary_official` | `metalltorg`, `official_html`; preferred MVP scope is only the parent `Строительные материалы` listing | 2GIS fallback is persisted: 18 source products, latest successful scrape 2026-05-17 | M14 smoke on 2026-05-22 used a conservative brick page and saved 1 product/snapshot. Follow-up research on 2026-05-23 validated the parent construction-material listing: 20 products per page, `data-all_count=1163`, about 59 listing pages. | HTML selectors are brittle; detail-page category enrichment adds about one request per new product | Use official HTML source for the construction-material section; defer other Metalltorg sections until separately researched |
| Евролайн | `fallback_2gis` | None confirmed for MVP | 2GIS branch `70000001007229923` | 106 source products; latest successful scrape 2026-05-17 | Category quality notes include SIP panels and insulation false negatives | Keep enabled as fallback source; review category gaps in M14 |
| Пирамида | `fallback_2gis` | None confirmed for MVP | 2GIS branch `7037402698836780` | 48 source products; latest successful scrape 2026-05-17 | Contains likely out-of-scope `Мебель` products; dry-mix coverage looks useful | Keep enabled, but filter/review noisy categories before public launch |
| Ондулин | `fallback_2gis` | None confirmed for MVP | 2GIS branch `7037402698774152` | 183 source products; latest successful scrape 2026-05-17 | Insulation raw category needs better mapping; some products mapped to greenhouse-related categories | Keep enabled; category review needed in M14 |
| Интехстрой | `fallback_2gis` | Official site exists, but no usable product/catalog signals were confirmed in M13 audit | 2GIS branch `7037402698745664` | 213 source products; latest successful scrape 2026-05-17 | Raw categories include межвенцовый утеплитель, штакетник, and likely out-of-scope household items | Keep 2GIS enabled; official source remains hold |
| Строительный мир / Орион-Экспрессия | `fallback_2gis` with official-source hold | Official site responded, but breadth still needs validation | 2GIS branch `70000001021201334` | 81 persisted source products in the current local DB; 2GIS validation saw 83 items; latest successful scrape 2026-05-17 | Generic `Материалы`, `Работа`, and special-purpose categories need review; official catalog may be narrower than core sources | Keep 2GIS enabled; create parser research only if M15 needs this shop as official |
| СибНорд | `hold_disabled` until parser implementation | Candidate official HTML source; follow-up #203 | 2GIS validation returned no priced products | No persisted local source rows in current snapshot | Bitrix pagination uses `PAGEN_1`, but robots policy disallows that pattern; broad pagination needs policy before schedule | Keep out of public MVP unless #203 is implemented and smoke-run |
| Востоктехторг | `hold_disabled` until parser implementation | Candidate official HTML source; follow-up #205 | 2GIS should stay held because it reports about 18.5k products and validated only partial slices | No persisted local source rows in current snapshot | Large catalog; prefer sitemap/configured pages until pagination and pacing policy are accepted | Keep out of public MVP unless #205 is implemented and smoke-run |
| Космос, ЛидерСтрой | `hold_disabled` | Official/source quality not accepted for MVP | 2GIS validation returned no prices | No persisted local source rows in current snapshot | No priced source data observed from 2GIS baseline | Keep out of scheduled collection |
| Decorative/plumbing/engineering shops from the M13 audit | `out_of_mvp_scope` | Later parser backlog only | None for MVP | Not part of current persisted baseline | Assortment is mostly decorative, plumbing, flooring, or engineering-adjacent | Revisit after core construction-material MVP |

## Release-Blocking Gaps

Move these into M14/M15 planning before public-site implementation depends on
shop/source data:

1. M14 complete: official-source readiness smoke for Юником and Металл Торг
   ([#211](https://github.com/dazeGG/stroyhub/issues/211)) confirmed seeded
   linked source records, latest successful scrape metadata, item counts, error
   count, and category quality notes.
2. M14 complete for official sources: Юником and Металл Торг source records are
   linked to shop identities with `preferred_source` set to the healthy official
   source. 2GIS fallback links remain source-specific and should be handled by
   public source-priority rules.
3. M14 complete: category-quality gaps for the currently fallback-ready 2GIS
   sources: insulation, SIP panels, generic `Материалы`, `Работа`, `Мебель`, and
   other obvious non-product cards
   ([#212](https://github.com/dazeGG/stroyhub/issues/212)).
4. M15: public MVP catalog must read from source-specific products and respect
   source priority; it should not merge cross-shop products until matching is
   intentionally reintroduced
   ([#210](https://github.com/dazeGG/stroyhub/issues/210)).
5. Ongoing parsers: #203 and #205 are not required for the first M15 cut unless
   СибНорд or Востоктехторг are chosen as launch-critical shops. If they become
   launch-critical, they block public MVP data readiness until parser, fixtures,
   scrape smoke, and robots/pacing policy are accepted.

## Pre-M15 Checklist

- [x] `unicom` official source is seeded, linked to a Юником identity, and has a
  recent successful or intentionally scoped partial scrape.
- [x] `metalltorg` official source is seeded, linked to a Металл Торг identity,
  and has a recent successful scrape for the configured category set.
- [ ] Large 2GIS catalogs for Юником and Востоктехторг remain disabled/held for
  scheduled collection unless a large-catalog mode is implemented.
- [x] Every public MVP source record has a clear status in admin:
  active/preferred, fallback, disabled/hold, or out of MVP scope.
- [x] Category quality notes for fallback 2GIS shops are reviewed and either
  fixed, documented as acceptable, or moved into M14/M15 issues.
- [ ] Public MVP product pages show source-specific shop attribution and do not
  imply cross-shop canonical matching.
