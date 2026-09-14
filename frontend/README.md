# Frontend

Next.js App Router. Admin panel (Phase 6) and user portal.

## Setup

```bash
cp .env.local.example .env.local
npm install
npm run dev          # http://localhost:3000
```

## Environments

Two files, never one with overrides:

| File | Loaded by |
|---|---|
| `.env.local` | `npm run dev`, `npm run build` (Next loads it automatically) |
| `.env.prod`  | `npm run build:prod`, `npm run start:prod` (explicit, via `dotenv-cli`) |

Only `NEXT_PUBLIC_*` values exist here and they are embedded in the browser
bundle — never put a secret in either file.

## Checks

```bash
npm run typecheck
npm run lint
```
