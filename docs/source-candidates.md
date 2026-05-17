# M8 Source Candidate Inventory

This document records Yakutsk construction-material shops found during M8 source
expansion research on 2026-05-17.

The lists are implementation planning input only. Before adding a parser, inspect
the source contract, capture focused fixtures, and update `docs/sources.md` with
source-specific details.

## Ready for Parsing Strategy

These sites have an observable product catalog and are ready for a dedicated
parsing strategy research issue.

| Shop | Site or catalog | Why it is ready | Likely strategy | Notes |
| --- | --- | --- | --- | --- |
| Юником | <https://unicom-ykt.ru/> | Public catalog exists and product pages are backed by a known JSON API. | JSON API client. | Best first M8 source. Existing notes mention `GET /api2/v-catalog-beta/products/{UUID}` and catalog menu discovery through `POST /api/catalog-menu-2.php`. |
| Металл Торг | <https://metalltorg.biz/catalog/> | Public catalog exists with construction-material categories and product cards. | HTML parsing, possibly Bitrix patterns. | Best first HTML source. Treat selectors as brittle and document sample category pages before implementation. |
| СибНорд | <https://sibnord.ru/> | Public catalog exists with construction categories such as dry mixes and construction materials. | Research JSON endpoints first, fall back to HTML parsing. | Good follow-up source after Юником and Металл Торг. |
| Востоктехторг | <https://vtt14.ru/catalog/> | Public catalog exists with construction and technical product categories. | Research JSON endpoints first, fall back to HTML parsing. | Large catalog; avoid scheduled scraping until pagination and pacing are understood. |
| Строительный мир / Орион-Экспрессия | <https://orion-expressiya.ru/> | Site exposes a store/catalog section and product cards. | HTML parsing. | Likely narrower than the main construction-material stores. Validate category coverage before prioritizing. |
| Космос | <https://kosmos-ykt.ru/catalog> | Public catalog exists. | HTML parsing. | More focused on finishing and repair materials than broad construction materials. |
| Космос Декор / RoomStyle | <https://roomstyledecor.ru/> | Public catalog-like sections exist, including related goods. | HTML parsing. | Narrow decorative coatings source; lower priority for MVP catalog breadth. |
| ТехноНиколь | <https://shop.tn.ru/> | Public catalog exists and 2GIS advertises catalog access for Yakutsk-related search results. | Research official storefront/API behavior. | Confirm Yakutsk-specific prices, availability, and branch context before parsing. |

## Candidates to Recheck Later

These sites were found from Yakutsk construction-material search or adjacent web
research, but should not be parsed until the stated blocker is resolved.

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
- For M8, prioritize one structured JSON source and one HTML source before adding
  more candidate parsers.
