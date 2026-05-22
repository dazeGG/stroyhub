# Source Fixture Strategy

This document defines how StroyHub stores and maintains source-specific test
fixtures for brittle external catalog contracts.

## Goals

- Keep parser and client tests offline by default.
- Preserve representative source response shapes without committing large dumps.
- Make fixture updates deliberate when a source contract changes.
- Keep parsers source-specific while mapping all products into the shared
  `ParsedProduct` contract.

## Folder Convention

Store observed source fixtures under:

```text
tests/fixtures/<source>/
```

Use the source slug that appears in parser code and persisted records:

- `tests/fixtures/unicom/`
- `tests/fixtures/metalltorg/`
- `tests/fixtures/sibnord/` for the accepted SibNord parser follow-up.
- `tests/fixtures/vostoktechtorg/` for the accepted Vostoktechtorg parser
  follow-up.
- `tests/fixtures/twogis/` if future 2GIS tests need captured samples.

Filename pattern:

```text
<contract-or-page>-<scenario>.<extension>
```

Examples:

- `catalog-menu-excerpt.json`
- `products-cement-page1.json`
- `category-stroitelnye-materialy-page1.html`
- `product-card-missing-price.html`

Use `.json` for API payloads and `.html` for captured HTML pages or focused
HTML fragments.

## Fixture Size Rules

Fixtures should be small and focused:

- keep only the fields needed to prove parser/client behavior;
- prefer one or two representative products over a full category dump;
- include edge cases as separate fixtures instead of one oversized file;
- avoid binary assets, screenshots, and downloaded images;
- avoid personal data, cookies, tokens, analytics payloads, and session ids;
- keep raw payload shape intact where possible, even when trimming unrelated
  items.

For JSON API fixtures, preserve source field names and string-vs-number behavior.
For HTML fixtures, preserve the relevant DOM structure around selectors, prices,
pagination, image references, and category breadcrumbs.

## Inline Payloads vs Fixtures

Inline payloads in tests are acceptable when they are synthetic and tiny, for
example:

- testing missing optional fields;
- testing invalid JSON or HTTP status handling;
- testing pagination stop conditions with minimal artificial pages;
- testing normalization helpers.

Use files under `tests/fixtures/<source>/` when a test depends on an observed
external source contract, for example:

- Unicom catalog menu tree shape;
- Unicom product response fields;
- Metalltorg product card selectors;
- Metalltorg pagination or missing-price HTML cases.

The existing 2GIS tests mostly use tiny inline payloads for unit behavior. That
fits this convention. If future 2GIS tests rely on larger captured responses,
move those samples into `tests/fixtures/twogis/`.

## Update Process

When a source contract changes:

1. Reproduce the change with an explicit live/debug command or focused manual
   request. Do not add live network calls to default tests.
2. Update or add the smallest fixture that demonstrates the new behavior.
3. Add or adjust parser/client tests that consume the fixture.
4. Update `docs/sources.md` with any lasting source-contract decision or
   assumption.
5. Mention the fixture change in the issue or pull request, including the source
   date and affected endpoint/page.

If an old fixture no longer represents a supported contract, replace it instead
of keeping stale variants around. Keep historical notes in docs or issue comments
when the contract change matters for future debugging.

## M8 Source Notes

M8 is complete as of 2026-05-18. Unicom and Metalltorg are the implemented
secondary sources from that milestone.

Unicom is the first M8 JSON source with focused fixtures:

- `tests/fixtures/unicom/catalog-menu-excerpt.json`;
- `tests/fixtures/unicom/products-cement-page1.json`.

Metalltorg uses focused HTML fixtures for parser and CLI tests:

- `tests/fixtures/metalltorg/category-kirpich-page1.html`;
- `tests/fixtures/metalltorg/product-kirpich-120420.html`.

Add smaller edge-case fixtures later when Metalltorg exposes missing prices,
pagination changes, or selector changes that need regression coverage.

SibNord research fixtures were captured on 2026-05-22 for the accepted parser
follow-up:

- `tests/fixtures/sibnord/category-tsement-peskobeton-page1.html`;
- `tests/fixtures/sibnord/product-63008.html`.

These are focused HTML fragments, not full page dumps. They preserve the Bitrix
product-card/detail selectors, embedded `JCCatalogItem`/`JCCatalogElement`
objects, prices, availability text, image paths, product ids, and category
breadcrumbs needed for parser characterization.

Vostoktechtorg research fixtures were captured on 2026-05-22 for the accepted
parser follow-up:

- `tests/fixtures/vostoktechtorg/category-stroitelnye-materialy-page1.html`;
- `tests/fixtures/vostoktechtorg/product-223784.html`.

These are focused HTML fragments from the Bitrix/Aspro catalog. They preserve
product card selectors, section links, pagination metadata, schema.org offer
metadata, stock quantities, article codes, image paths, and the
`setViewedProduct` detail-page object.
