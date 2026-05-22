# CLAUDE.md

See [AGENTS.md](AGENTS.md) for full project instructions. This file adds only Claude Code-specific context.

## Language

Always respond in Russian.

## Workflow

For non-trivial tasks:
1. Discuss the approach with the user first
2. Create a GitHub Issue in the current milestone
3. Then implement

## Project Context

### ML Training Flow

`apps/ml/` is a local, offline CLI toolset. Model training is **not** integrated with Celery or the worker — do not suggest it. Flow: collect data via CLI → build dataset snapshot → train locally → load via runtime loader.

### apps/admin

`apps/admin` is a Vue/Vite admin panel for service administration, not the product-facing frontend. A separate product frontend is planned as another app in `apps/`.

### Database Repositories

All repositories live in one file: `packages/stroyhub/db/repositories.py`. Do not propose splitting it.
