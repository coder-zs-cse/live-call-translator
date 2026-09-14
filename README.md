# Live Call Translator

Real-time, two-way phone translation for Indian languages. Two people dial the
same number, get paired, and each hears only the other person's speech
translated into their own language.

> **Status: Phase 0.** The skeleton boots and the provider layer is real, but no
> call has been translated yet. Read [docs/PLAN.md](docs/PLAN.md) first — it
> holds the architecture, the phased roadmap, and the decisions that are
> deliberately deferred.

## Layout

```
backend/    FastAPI control plane + (Phase 1) the Pipecat media plane
frontend/   Next.js admin panel and user portal
infra/      docker-compose for Postgres, Redis, MinIO
docs/       PLAN.md — read this before writing code
```

## Quick start

```bash
# dependencies
docker compose -f infra/docker-compose.yml up -d

# backend  -> http://localhost:8000/docs
cd backend
cp .env.local.example .env.local        # fill in SARVAM__API_KEY
uv sync --extra dev
uv run uvicorn app.main:app --reload --port 8000

# frontend -> http://localhost:3000
cd ../frontend
cp .env.local.example .env.local
npm install
npm run dev
```

## Environments

Each app keeps **one file per environment**, never a shared `.env` with
overrides layered on top:

| | local | prod |
|---|---|---|
| backend | `.env.local` | `.env.prod` (needs `APP_ENV=prod`) |
| frontend | `.env.local` | `.env.prod` (needs `npm run build:prod`) |

Both are git-ignored; the committed `.env.*.example` files are the templates.
Loading production config is always an explicit act — there is no path where it
happens by default.

## Phase 0: run the spike first

The plan rests on one unverified assumption: that Sarvam translates Indic to
Indic directly rather than pivoting through English. A pivot roughly doubles
that stage's share of the 2-second latency budget. Measure it before building
the pipeline:

```bash
cd backend && uv run python scripts/spike_translation.py
```

It prints a latency table, a pivot verdict, and sample translations to read
yourself — the register and code-mixing questions need human judgement, not an
assertion.

## Checks

```bash
cd backend  && uv run ruff check . && uv run mypy app && uv run pytest
cd frontend && npm run typecheck && npm run lint
```
