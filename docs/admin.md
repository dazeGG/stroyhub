# Admin UI

M12 adds a dedicated admin/review interface for inspecting StroyHub data quality
and scraper health.

## Location

The admin UI lives in:

```text
apps/admin/
```

It is a separate frontend application. It talks to `apps/api` over HTTP and must
not import Python modules from `packages/stroyhub` directly.

## Starter Stack

- Vue 3 for UI components.
- Vite for development and production builds.
- TypeScript for application code.
- Tailwind CSS for layout, spacing, and custom styling.
- Nuxt UI as the Tailwind-based Vue component library through its Vite plugin.
- Vue Router for admin pages.
- pnpm with the active Node.js LTS line for frontend dependency management.

Nuxt UI is used as a Vue component library. M12 does not adopt Nuxt as the app
framework.

Add Pinia, a charting package, or generated API clients only when an implemented
screen needs them.

## Initial M12 Jobs

The first admin version should help a human answer these questions without
terminal commands:

- What products have we scraped, from which shop, in which category, and at
  what latest price?
- How has a selected product price changed across scrape observations?
- Which shops or sources are failing, stale, or scraping successfully?
- Which products are uncategorized, questionably categorized, or grouped under
  noisy source categories?
- Which future product-match candidates need human review, if matching
  persistence and API support are ready by then?

## Initial Screens

- Product catalog inspection: searchable/filterable table with title, shop,
  normalized category, raw category, latest price, and last-seen metadata.
- Product detail: source payload summary, latest price, and price history.
- Scrape status dashboard: shop scrape status, next/last scrape metadata,
  recent runs, and visible failed/partial runs.
- Category quality review: unmatched or suspicious groups by `category_raw`,
  representative titles, and copy/export support for follow-up issues.
- Match candidate review: read-only candidate comparison or postponed until the
  matching persistence/API surface is ready.
