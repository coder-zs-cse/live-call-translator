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
assertion. Results are recorded in [docs/PLAN.md](docs/PLAN.md) §7.4.1.

## Phase 1: the echo test

The media path is built and proven against a simulated Vobiz:

```bash
cd backend && uv run pytest tests/integration -q
```

To confirm it on a **real call**, Vobiz needs a public URL for this machine:

```bash
cloudflared tunnel --url http://localhost:8000        # or: ngrok http 8000
```

Put the tunnel origin in `backend/.env.local` as `VOBIZ__PUBLIC_BASE_URL`,
restart the backend, then point your Vobiz application's Answer URL at
`<tunnel>/api/v1/xml/answer` and dial the number.

You should hear your own voice come back. Two things to listen for, because
they are what this phase exists to rule out: **jitter** (choppy or robotic
audio) and **doubling** (hearing yourself twice). The first `start` frame is
logged in full — that is what pins down the field spellings Vobiz does not
document.

**Status: confirmed on a real call.** Clear audio, no jitter.

## Phase 2: hear yourself translated

Same setup as Phase 1, but `PIPELINE__MODE=translate_loopback` (the default).
Speak the source language, hear the target language back:

```bash
# in backend/.env.local
PIPELINE__MODE=translate_loopback
PIPELINE__LOOPBACK_SOURCE_LANGUAGE=hi-IN
PIPELINE__LOOPBACK_TARGET_LANGUAGE=ta-IN
PIPELINE__VAD_STOP_SECONDS=0.7          # the main latency knob
```

Set `PIPELINE__MODE=echo` to drop back to the Phase 1 bot when you need to tell
a plumbing problem from an AI one.

Expect roughly 3 seconds end to end. That is measured, not a bug — see
[docs/PLAN.md](docs/PLAN.md) §7.4.2 for where it goes and what would claw it
back.

## Translation eval

Compares configurations on a fixed dataset. Latency is identical across Sarvam
modes, so this is a quality tool:

```bash
cd backend
uv run python scripts/eval_translation.py --variants code-mixed,formal
```

`eval/dataset.jsonl` carries the known failure cases as rows, so a future change
gets measured against them instead of argued about. Every `reference` field
starts `null` on purpose — writing reference translations is human work, and
inventing them would make the harness lie. Fill some in and chrF scoring turns
itself on.

## Checks

```bash
cd backend  && uv run ruff check . && uv run mypy app && uv run pytest
cd frontend && npm run typecheck && npm run lint
```
