# StroyHub Admin

Vue-based admin/review UI for StroyHub operators.

## Stack

- Vue 3
- Vite
- TypeScript
- Tailwind CSS
- Nuxt UI
- Vue Router
- pnpm
- Node.js 22.12+

## Local Development

Install frontend dependencies:

```bash
cd apps/admin
pnpm install
```

Run the admin API from the repository root:

```bash
uv run uvicorn apps.admin_api.main:app --port 8001 --reload
```

Run the admin UI:

```bash
cd apps/admin
pnpm dev
```

The Vite dev server proxies `/api/*` requests to `http://127.0.0.1:8001/*`.
Set `VITE_API_BASE_URL` to override the default API base path.

## Design Tokens

Admin colors are defined in `src/style.css` as local `admin-*` Tailwind theme tokens backed by CSS custom properties. Do not override the default Tailwind palette; use the StroyHub tokens for admin semantics.

- Use `admin-bg`, `admin-surface`, `admin-surface-muted`, and `admin-border` for the light black-and-white shell, panels, tables, and form controls.
- Use `admin-text`, `admin-text-muted`, and `admin-text-faint` for copy hierarchy.
- Use `admin-primary` for primary actions. The primary/accent color is black.
- Use `admin-success`, `admin-warning`, and `admin-danger` only for status feedback or risk states, not for general decoration.

## Checks

```bash
pnpm typecheck
pnpm build
```
