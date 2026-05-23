# Decisions

## 2026-05-16: Start the MVP in Python

Context:
StroyHub is data-heavy: unstable source APIs, HTML parsing, product normalization, categorization, and future ML experiments matter more than raw service throughput during the MVP.

Decision:
Build the MVP in Python and keep the codebase structured enough that scraper, API, or worker pieces can be split out later if needed.

Consequences:
Python remains the default language for the first implementation. Go or Rust can be reconsidered after the data model and scraping behavior are proven.

## 2026-05-16: Use a Python Monorepo With Thin Apps

Context:
The API, worker, CLI scripts, and tests all need the same parser, catalog, scraping, and database logic. Putting that logic under the API package would make FastAPI the accidental center of the system.

Decision:
Keep runnable entrypoints in `apps/` and reusable logic in `packages/stroyhub`.

Consequences:
`apps/api`, `apps/admin_api`, and `apps/worker` should stay thin. They may
import `stroyhub`, but `stroyhub` should not import app modules.

## 2026-05-16: Do Not Create Separate App Packages Yet

Context:
An earlier layout used `stroyhub_api` and `stroyhub_worker` as installable app packages. That was technically tidy, but heavier than needed for the current project.

Decision:
Use direct modules such as `apps/api/main.py`, `apps/admin_api/main.py`, and
`apps/worker/celery_app.py`.

Consequences:
The project is easier to scan. If the API or worker grows into a separately distributed package later, it can be split deliberately.

## 2026-05-21: Build the M12 Admin UI as a Separate Vue App

Context:
M11 exposed the catalog API surface needed by future UI and admin screens.
M12 needs a lightweight interface for inspecting source products, price
history, scrape health, category quality, and future review queues. The
admin is expected to become interactive enough that filters, tables, detail
panels, charts, and review workflows should live in a dedicated frontend rather
than in server-rendered backend templates. This is an explicit project decision
to introduce a Node/Vite frontend toolchain for the admin app only.

Options considered:

- Extend `apps/api` with HTML routes: simplest startup path, but it mixes JSON
  API composition with admin screen concerns.
- Add a Python-rendered admin app under `apps/admin`: keeps the stack minimal,
  but makes richer table, chart, and review interactions more awkward.
- Add a Vue/Vite admin app under `apps/admin`: introduces frontend tooling, but
  keeps the UI boundary clean and matches the expected admin interaction model.

Decision:
Add the admin/review interface as `apps/admin`, a separate Vue frontend app
alongside `apps/api` and `apps/worker`. Use Vue 3, Vite, TypeScript, Tailwind
CSS, Nuxt UI components, Vue Router, and pnpm with the active Node.js LTS line.
Use Nuxt UI as a Vue component library through its Vite plugin; do not adopt
Nuxt as the application framework for M12.

The admin app should consume JSON endpoints from the backend over HTTP. Shared
business logic remains in `packages/stroyhub` and is exposed to the admin via
API endpoints, not direct frontend imports. Add Pinia, a charting package, or a
generated API client only when the first implemented screens make the need
concrete.

Initial M12 scope:

- Product catalog inspection with search, shop/category filters, latest price,
  and last-seen metadata.
- Product detail with price history.
- Scrape status dashboard with shop scrape metadata and recent runs.
- Category quality review focused on unmatched or low-confidence data.
- Product match candidate review as a read-only or postponed screen unless the
  matching persistence/API surface is ready.

Consequences:
The admin UI gets its own routing, components, static assets, dependency lock,
and tests without turning the backend API into an HTML controller. The project
now has two toolchains: Python/uv for backend, worker, scraping, and domain
code; Node/pnpm for `apps/admin`. Frontend dependencies should stay scoped to
`apps/admin` unless a later decision broadens the JavaScript footprint.

## 2026-05-16: Manage Python With uv

Context:
The project should not depend on whatever Python or packages happen to be installed globally on a developer machine.

Decision:
Pin Python with `.python-version`, lock dependencies with `uv.lock`, and create the local virtual environment with `uv sync --all-extras`.

Consequences:
`.venv` is local and ignored. `uv.lock` is committed. Development commands should prefer `uv run ...`.

## 2026-05-16: Store Source Product Cards Before Canonical Products

Context:
Construction material names vary heavily between shops. Trying to perfectly merge products before collecting data would slow down the MVP and likely create brittle assumptions.

Decision:
Model source product cards first. Add canonical products and product matching after enough examples have been collected.

Consequences:
The initial API may show multiple cards that are semantically the same product. That is acceptable for the MVP because price history and source fidelity are the first priority.

## 2026-05-16: Store Every Price Observation

Context:
If price history only records changed prices, the system cannot distinguish an unchanged price from a missing product or failed scrape.

Decision:
Write one `price_snapshots` row for every successful observed product price during scraping.

Consequences:
The table will grow faster, but the data will be easier to reason about during the MVP. Deduplication or separate observation tables can be considered later if volume becomes a real problem.

## 2026-05-16: Match Source Products by Source ID First, Fingerprint Second

Context:
Sources may or may not provide stable product identifiers. HTML sources are especially likely to lack stable IDs.

Decision:
When `source_product_id` exists, match source products by `source`, `shop_id`, and `source_product_id`. When it does not, use a best-effort `fingerprint` built from normalized stable fields.

Consequences:
Stable source IDs give reliable updates. Fingerprints may create duplicates when product names change, which is acceptable until canonical product matching is introduced.

## 2026-05-17: Start Categorization With Rules Before ML

Context:
The MVP needs category filtering before there is enough data for useful ML-based classification.

Decision:
Use a rule-based categorizer with explicit construction-material keyword dictionaries. The service returns a category slug, display name, confidence, matched keywords, and source. During scraping persistence, matched categories are upserted into `categories` and assigned to `source_products.category_id`.

Manual category overrides are represented at the service level: a provided override takes precedence over rules and returns confidence `1.0` with source `manual_override`. A dedicated override table can be added later if an admin UI or audit trail needs it.

Consequences:
Initial categories are explainable and easy to adjust. Some products will remain uncategorized until rules are expanded from real scrape data.

## 2026-05-22: Treat MVP Categories as Two-Level Taxonomy

Context:
StroyHub needs category navigation and ML category verification to stay simple
while the catalog is still being shaped from real source data.

Decision:
Use a two-level taxonomy policy for the MVP:

- root categories are grouping/navigation sections;
- child categories are assignable product categories;
- products, manual overrides, ML labels, and future ML predictions target
  child/leaf categories only;
- root categories should not receive products directly.

Consequences:
The database keeps the flexible `parent_id` hierarchy and does not enforce this
policy at schema level. This preserves room for future taxonomy changes without
rewriting the schema, while current product, admin, and ML workflows treat the
taxonomy as two-level.

## 2026-05-18: Persist Manual Category Overrides Separately

Context:
M9 adds source category aliases, safer keyword matching, and category quality
reports. Once an admin/review workflow exists, reviewers need manual category
corrections that survive rescrapes without rewriting source product cards or
hard-coding every exception into rule dictionaries.

Decision:
Store manual category corrections in a dedicated `category_overrides` table
linked to `source_products` and `categories`. During categorization,
persisted manual overrides take precedence over source category aliases and
rule-based predictions. The existing in-memory `ManualCategoryOverride` service
object remains the runtime representation of that highest-precedence decision.

Consequences:
Manual decisions are auditable and reversible. Source data remains intact, and
rules/aliases can still improve general coverage without hiding reviewer-made
exceptions. The implementation lives in `category_overrides`, with active
overrides exposed through product API responses.

## 2026-05-22: Keep ML Workflows in a Separate Workspace App

Context:
Category verifier and predictor work needs dataset collection, snapshots,
training, evaluation, model artifacts, and reports. Those are project utility
workflows, not operational catalog data. The product database should stay
focused on source products, categories, prices, scrapes, and admin decisions.

Decision:
Use `apps/ml` for ML commands and `.var/ml` for runtime ML artifacts. Keep
reusable model code in `packages/stroyhub/ml`. The first dataset collection
workflow is CLI-first and reads products/categories from PostgreSQL directly.
It stores live labels in `.var/ml/category_verifier/labels.jsonl`, creates
versioned dataset snapshots before training, and writes trained model artifacts
under `.var/ml/category_verifier/models`.

`apps/api` and `apps/worker` may use ready models through public APIs from
`packages/stroyhub/ml`, but they do not train models and do not import model
implementation internals directly. `apps/admin` remains an operational review
UI; it can review suggestions exposed by the API, but it does not collect ML
training labels.

Consequences:
ML labels, snapshots, models, and reports are not committed to git and are not
stored in PostgreSQL. A single CLI labeling answer can support both category
verifier training and a future category predictor. Operational category changes
continue to use manual overrides or accepted suggestion review, not raw ML
labels.

## 2026-05-22: Defer ML From the First MVP Release

Context:
The first category verifier experiment (`v001`) was trained on 100 labeled
products. It showed useful signal, but the dataset, thresholds, and evaluation
coverage are not mature enough to influence the first release. The MVP still
needs reliable scraping, price history, catalog search, category review, and
manual correction workflows before ML adds enough operational value.

Decision:
Do not include ML-driven category verification, prediction, suggestions, or
automatic category changes in the first MVP release scope. Keep the existing
`apps/ml` and `packages/stroyhub/ml` code as experimental/offline workspace
infrastructure, but treat it as post-MVP work unless a later release decision
reopens it.

Consequences:
MVP product behavior should rely on source data, rule/alias categorization,
manual category overrides, and admin review workflows. API, worker, and admin
features for the first release should not depend on trained model artifacts or
`.var/ml` runtime files. ML docs and code may stay in the repository for later
experimentation, but ML tasks should not block the first release.

## 2026-05-22: Prefer Official Shop Catalogs Over 2GIS When Available

Context:
2GIS helped bootstrap the first Yakutsk product dataset, but it is an
unofficial source for product cards. Some shops expose their own public catalogs
or APIs, which are more likely to have fresher prices, better category context,
and clearer ownership of product data.

Decision:
For M13 and later product work, prefer official shop APIs or official shop
catalog pages over 2GIS for shops where those official sources are usable. Keep
2GIS as a discovery, fallback, and coverage source, especially for shops without
a usable official catalog.

Consequences:
Source product cards remain source-specific and should not be destructively
merged when the same real-world shop appears in both 2GIS and an official
source. M13 should define shop identity and source priority rules before the
public MVP site depends on shop/product display choices. The detailed policy is
tracked in `docs/sources.md`.

## 2026-05-22: Add Shop Identity Grouping Before Public Shop Display

Context:
The same real-world shop or store location can appear as multiple source-specific
records, such as an official catalog source and a 2GIS branch. Keeping those
records separate preserves source fidelity, but admin and public-site flows need
a stable human-facing shop identity for display, review, and source priority.

Decision:
Design M13 around an explicit shop identity grouping concept. Source-specific
`shops` records remain scrape targets and retain their source/source-id
identity. A future `shop_identities` grouping layer should connect source
records that represent the same real-world shop/location and record preferred
source behavior for admin and public-site display.

Consequences:
M13 needs a database follow-up for the grouping schema and API/admin follow-ups
for managing linked source records. `source_products` stay attached to
source-specific `shops`; shop identity grouping must not become product
canonical matching or destructive source merging. The detailed policy is tracked
in `docs/sources.md`.

## 2026-05-18: Accept Conservative Product Matching Schema

## 2026-05-23: Split Public and Admin HTTP APIs

Context:
The previous FastAPI entrypoint mixed public catalog reads with admin/operator
workflows (match review, normalization queue, candidate management, and scrape
operations). This increased API contract churn risk before starting the public
MVP frontend.

Decision:
Split HTTP entrypoints into:

- `apps/api/main.py` for public read-only catalog routes.
- `apps/admin_api/main.py` for admin/operator routes.

Keep shared business logic in `packages/stroyhub`. The admin frontend proxy now
targets the admin API service.

Consequences:
Public OpenAPI becomes stable and safer for frontend consumption. Admin APIs
can evolve without exposing operator endpoints in the public surface.

Context:
M10 implemented a pure in-memory product matching prototype before adding
database tables. The prototype accepts `SourceProduct`-like records and returns
candidate pairs with confidence and explainable reason metadata. It supports
exact normalized-title matches, token-similarity review candidates, and hard
blockers for conflicting weights, package counts, dimensions, grades, and finish
colors. A report CLI can list candidate pairs before any persistence is added.

Decision:
Accept the `canonical_products` and `product_matches` schema described in
`docs/database.md` for M10 implementation. `canonical_products` represents a
source-neutral grouped product identity. `product_matches` links source product
cards to canonical products and stores confidence, status, method, review
metadata, and reason JSON.

Consequences:
Source product cards remain the immutable source-of-truth records. Matching is
additive and reviewable; it must not delete, rewrite, or merge
`source_products`. Medium-confidence candidates stay reviewable instead of being
accepted automatically. Embeddings, destructive cross-shop merges, automatic
price-unit normalization, and admin accept/reject workflows remain out of scope
for this schema step. Migration implementation is tracked in
[#63](https://github.com/dazeGG/stroyhub/issues/63).
