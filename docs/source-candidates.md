# Source Candidate Inventory

This document records Yakutsk construction-material shops found during source
expansion research.

M8 is complete as of 2026-05-18. It promoted two sources from research into
implemented source support:

- `Юником`: JSON API client, parser normalization, and scrape persistence flow.
- `Металл Торг`: HTML catalog research, parser, and debug scrape CLI.

M13 uses this inventory to decide which official shop catalogs should supersede
or complement 2GIS before the public product site is built.

The M13 end-of-milestone shop/source readiness checklist lives in
`docs/shop-readiness.md`.

The lists are implementation planning input only. Before adding a parser, inspect
the source contract, capture focused fixtures, and update `docs/sources.md` with
source-specific details.

## M13 Official Source Audit

Audit date: 2026-05-22.

Method:

- Review the M8 candidate inventory.
- Run a lightweight HTTP/HTML smoke check against official shop sites.
- Classify each candidate for M13 planning.
- Do not persist large page dumps from live sites.

Status values:

- `implemented`: parser/client support exists; M13 should operationalize it.
- `ready_for_parser_research`: good official-source candidate, but source
  contract research is still needed.
- `hold`: relevant source, but not a first M13 implementation target.
- `out_of_mvp_scope`: useful later, but not central to the construction-material
  MVP.

MVP priority ranking:

1. `Юником`: official JSON API is already implemented; make it a scheduled
   official source before relying on its very large 2GIS catalog.
2. `Металл Торг`: official HTML parser exists; promote the official catalog from
   debug support into repeatable collection if selector health remains good.
3. `СибНорд`: official site exposes catalog-like construction-material pages;
   research this before treating the empty/no-price 2GIS result as final.
4. `Востоктехторг`: official catalog may solve the very large partial 2GIS
   scrape problem, but catalog size and pacing need research first.

| Shop | Official site/catalog | M13 status | Official source should supersede 2GIS? | Priority | Follow-up | Notes |
| --- | --- | --- | --- | ---: | --- | --- |
| Юником | <https://unicom-ykt.ru/> | `implemented` | Yes, for prices/products/categories when official API coverage is sufficient. | 1 | [#187](https://github.com/dazeGG/stroyhub/issues/187) | Public site responded with product/catalog signals; existing JSON API details live in `docs/sources.md`. |
| Металл Торг | <https://metalltorg.biz/catalog/> | `implemented` | Yes, if HTML parser health is acceptable. | 2 | [#188](https://github.com/dazeGG/stroyhub/issues/188) | Public catalog responded and existing parser fixtures are available. |
| СибНорд | <https://sibnord.ru/> | `ready_for_implementation` | Yes for official prices and availability once parser health is accepted. | 3 | [#189](https://github.com/dazeGG/stroyhub/issues/189), [#203](https://github.com/dazeGG/stroyhub/issues/203) | Bitrix HTML catalog with priced product cards and product detail pages. Pagination uses `PAGEN_1`, but `robots.txt` disallows that pattern, so scheduled broad pagination needs an explicit policy decision before collection. |
| Востоктехторг | <https://vtt14.ru/catalog/> | `ready_for_implementation` | Yes for official prices, stock, and category context once parser health is accepted. | 4 | [#190](https://github.com/dazeGG/stroyhub/issues/190), [#205](https://github.com/dazeGG/stroyhub/issues/205) | Bitrix/Aspro HTML catalog with priced product cards, stock quantities, article codes, product detail pages, and sitemap `lastmod`. The construction-material section reports 537 products across 27 pages, but `robots.txt` disallows `?PAGEN`, so prefer sitemap/configured pages until pagination policy is accepted. |
| Строительный мир / Орион-Экспрессия | <https://orion-expressiya.ru/> | `hold` | Maybe, after category breadth is validated. | 5 | None yet | Site responded with shop/product signals, but likely narrower than core construction-material sources. |
| Космос | <https://kosmos-ykt.ru/catalog> | `hold` | Maybe, especially if official site has prices while 2GIS has none. | 6 | None yet | Site responded with catalog and price signals; assortment looks more tools/finishing oriented. |
| АБК-Фасад | <https://yakutsk.abk-fasad.ru/> | `hold` | Yes for facade/insulation scope, later. | 7 | None yet | Site responded with catalog and price signals; good facade/insulation source but not a first M13 parser target. |
| Центр Металлокровли | <https://yakutsk.centermk.ru/> | `hold` | Yes for roofing/metal scope, later. | 8 | None yet | Site responded with catalog and product signals; useful once roofing breadth is prioritized. |
| Якутск-Строй | <https://www.yakutsk-stroy.ru/products/> | `hold` | Maybe, but source quality must be validated. | 9 | None yet | Catalog pages responded, but price signals were not observed in the light smoke check. |
| ТехноНиколь | <https://shop.tn.ru/> | `hold` | Unknown until storefront access and Yakutsk context are confirmed. | 10 | None yet | Public storefront returned `403` to the lightweight HTTP check; browser/manual research is needed before planning a parser. |
| Космос Декор / RoomStyle | <https://roomstyledecor.ru/> | `out_of_mvp_scope` | No for core MVP; revisit for decorative coatings. | - | None | Site responded but price/product signals are weak and assortment is narrow. |
| Братья Марио | <https://santehnika-ykt.ru/> | `out_of_mvp_scope` | No for core MVP; revisit for сантехника. | - | None | Catalog/product signals exist, but assortment is mostly plumbing. |
| Ин-Тек | <https://1n-tek.ru/> | `out_of_mvp_scope` | No for core MVP. | - | None | Connection refused during light HTTP check; assortment is adjacent engineering equipment. |
| Сталепромышленная компания | <https://yakutsk.spk.ru/> | `hold` | Maybe for metal products after access check. | - | None | Connection refused during light HTTP check; local catalog/store availability still needs validation. |
| Интехстрой | <https://its96.ru/> | `hold` | Unknown. | - | None | Site responded, but no product/catalog signals were observed in the light smoke check. |
| Квадратура | <https://yakutsk.kwadratura.ru/> | `out_of_mvp_scope` | No for core MVP; revisit for finishing/flooring. | - | None | Site responded with catalog/price signals, but assortment is mostly finishing materials and flooring. |
| UIK-RUS | <https://jakutsk.uik-rus.ru/> | `hold` | Unknown until access is reliable. | - | None | Timed out during light HTTP check; retry manually/browser before planning parser work. |

## Historical M8 Ready for Parsing Strategy

These sites were observed during M8 and kept as historical planning input. Use
the M13 audit above for current priority and status.

| Shop | Site or catalog | Why it is ready | Likely strategy | Notes |
| --- | --- | --- | --- | --- |
| Юником | <https://unicom-ykt.ru/> | Public catalog exists and product pages are backed by a known JSON API. | Implemented JSON API client and persistence flow. | M8 implemented source. Details live in `docs/sources.md`; focused fixtures live under `tests/fixtures/unicom/`. |
| Металл Торг | <https://metalltorg.biz/catalog/> | Public catalog exists with construction-material categories and product cards. | Implemented HTML parser and debug CLI. | M8 implemented source. Treat selectors as brittle; focused fixtures live under `tests/fixtures/metalltorg/`. |
| СибНорд | <https://sibnord.ru/> | Public catalog exists with construction categories such as dry mixes and construction materials. | Research JSON endpoints first, fall back to HTML parsing. | Good follow-up source after Юником and Металл Торг. |
| Востоктехторг | <https://vtt14.ru/catalog/> | Public catalog exists with construction and technical product categories. | Research JSON endpoints first, fall back to HTML parsing. | Large catalog; avoid scheduled scraping until pagination and pacing are understood. |
| Строительный мир / Орион-Экспрессия | <https://orion-expressiya.ru/> | Site exposes a store/catalog section and product cards. | HTML parsing. | Likely narrower than the main construction-material stores. Validate category coverage before prioritizing. |
| Космос | <https://kosmos-ykt.ru/catalog> | Public catalog exists. | HTML parsing. | More focused on finishing and repair materials than broad construction materials. |
| Космос Декор / RoomStyle | <https://roomstyledecor.ru/> | Public catalog-like sections exist, including related goods. | HTML parsing. | Narrow decorative coatings source; lower priority for MVP catalog breadth. |
| ТехноНиколь | <https://shop.tn.ru/> | Public catalog exists and 2GIS advertises catalog access for Yakutsk-related search results. | Research official storefront/API behavior. | Confirm Yakutsk-specific prices, availability, and branch context before parsing. |

## Historical M8 Candidates to Recheck Later

These sites were found from Yakutsk construction-material search or adjacent web
research during M8. Use the M13 audit above for current priority and status.

| Shop | Site | Reason to hold | Next check |
| --- | --- | --- | --- |
| Братья Марио | <https://santehnika-ykt.ru/> | Catalog exists, but the assortment is mostly сантехника and adjacent goods rather than core construction materials. | Revisit when plumbing/heating categories become in-scope. |
| Ин-Тек | <https://1n-tek.ru/> | Catalog exists, but the assortment appears focused on climate, water supply, and equipment. | Revisit when engineering equipment sources become in-scope. |
| Сталепромышленная компания | <https://yakutsk.spk.ru/> | Metal products are relevant, but the local catalog/store availability needs a separate access check. | Confirm Yakutsk-specific catalog pages and scrape access. |
| Интехстрой | <https://its96.ru/> | Site is present in 2GIS, but a usable product catalog was not confirmed during the initial check. | Recheck manually or through browser before creating a parser issue. |
| АБК-Фасад | <https://yakutsk.abk-fasad.ru/> | Catalog exists, but the source was found outside the initial 2GIS `стройматериалы` candidate pass. | Add to the M8 backlog if facade/insulation breadth is prioritized. |
| Квадратура | <https://yakutsk.kwadratura.ru/> | Catalog exists, but assortment is mostly finishing materials and flooring. | Revisit for finishing-material expansion. |
| Якутск-Строй | <https://www.yakutsk-stroy.ru/products/> | Product catalog exists, but source quality and product detail structure need validation. | Inspect pagination, prices, and raw product card fields. |
| Центр Металлокровли | <https://yakutsk.centermk.ru/> | Relevant domain, but not part of the initial confirmed 2GIS catalog-source set. | Validate Yakutsk catalog and product availability. |
| UIK-RUS | <https://jakutsk.uik-rus.ru/> | Site was slow or timed out during the initial check. | Retry with browser/manual inspection before planning parser work. |

## Research Notes

- The initial 2GIS search used `стройматериалы` for Yakutsk on 2026-05-17.
- A site is considered ready only when a real product catalog or catalog-like
  product listing was observed.
- Advertising links, messenger links, and pure business-card pages are not enough
  to qualify a source for parsing.
- M8 prioritized one structured JSON source and one HTML source before adding
  more candidate parsers. Future parser work should start from the remaining
  candidates rather than reopening the completed M8 milestone.
