# StroyHub Admin

Vue-based admin/review UI for the M12 milestone.

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

## Checks

```bash
pnpm typecheck
pnpm build
```
