# Backend

FastAPI control plane + (from Phase 1) the Pipecat media plane.

## Setup

```bash
cp .env.local.example .env.local     # then fill in SARVAM__API_KEY etc.
uv sync --extra dev --extra media
docker compose -f ../infra/docker-compose.yml up -d
uv run uvicorn app.main:app --reload --port 8000
```

`APP_ENV` selects the settings file — `local` (default) reads `.env.local`,
`prod` reads `.env.prod`. There is no shared `.env`, on purpose: running against
production config has to be a deliberate act.

## Phase 0 spike

Answers the open question in `docs/PLAN.md` §7.4 before any pipeline code is
worth writing:

```bash
uv run python scripts/spike_translation.py --repeat 3
```

## Checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest
```
