# Live Call Translator — Design & Build Plan

A phone-based, real-time, two-way speech translator for Indian languages.
Two people dial the same AI number, get paired, and each hears only the other
person's speech translated into their own language.

Status: planning. Nothing built yet.

---

## 1. Scope

**In scope (v1)**
- Inbound DID on Vobiz, IVR menu, three pairing modes (create room / dial out / join room).
- Per-user language settings (primary + secondary, secondary drives code-mixed output).
- Two-leg server-side bridge with one-way translated audio per direction.
- Per-utterance observability (audio, transcript, translation, per-stage timings, cost).
- Next.js admin panel + phone-number login for end users.
- Config-driven rate limiting, blacklist, premium bypass.

**Explicitly out of scope (v1)**
- Barge-in / interruption handling. A speaker's utterance is always transmitted in full.
- Payments. Billing is *ledgered and displayed*, not charged.
- OTP login. Phone number in, session out, plus an admin bypass.
- Group calls (>2 legs), WhatsApp/app clients, offline mode.

**Deferred by decision (see §7.2 and §10)**
- **Acoustic echo / same-room feedback.** Assume the two parties are far enough
  apart that neither phone's speaker reaches the other's mic.
- **Horizontal scale.** Target is *one* call working end to end, on one process.

The goal of v1 is a single successful translated call. Everything below is
written against that target.

---

## 2. The one decision everything else hangs off

**Do not bridge the two callers at the carrier.** No `<Dial>`, no `<Conference>`.

If the carrier bridges them, both raw voices are already mixed into each leg's
audio before your code sees it. You then physically cannot deliver "translated
voice only" — you get the original underneath, and your STT hears both speakers
on both legs. That is the "double voice" failure mode in the NFRs, and it is
unfixable downstream.

Instead: **two independent calls, each streaming to your server, bridged in
software.**

```
Caller A ──PSTN──> Vobiz ──WS(A)──┐
                                  │   your media worker
                                  │   A.in ─> STT(hi) ─> MT(hi→ta) ─> TTS(ta) ─> B.out
                                  │   B.in ─> STT(ta) ─> MT(ta→hi) ─> TTS(hi) ─> A.out
Caller B ──PSTN──> Vobiz ──WS(B)──┘
```

Each leg is a call to *your application*, not to the other person. There is no
far-end audio on the leg at all, so "translated voice only" is true by
construction rather than by filtering. Cost: you pay for two legs per
conversation, and you own the bridge's reliability. Accept it.

Consequence to design around early: the two legs of one conversation **must
land in the same process** (§10).

---

## 3. Vendor capability check (verified, Sep 2026)

Checked before committing to the architecture, because the whole plan collapses
if any of these are false.

| Requirement | Status | Notes |
|---|---|---|
| Vobiz bidirectional WS audio | OK | Inbound `audio/x-l16` 8/16 kHz or `audio/x-mulaw` 8 kHz; outbound L16 8/16/24 kHz or mulaw 8 kHz |
| Vobiz: outbound audio played to caller, no echo of own voice | OK | Confirmed in streaming docs |
| Vobiz playback-completion signal | OK | `checkpoint` → `playedStream`, plus `clearAudio`/`clearedAudio` |
| Vobiz IVR DTMF | OK | `<Gather>`, DTMF **and** speech, simultaneous; digits POSTed to action URL |
| Vobiz inbound DID + outbound call API | OK | Answer URL app model; `POST /api/v1/Account/{auth_id}/Call/` |
| Pipecat ↔ Vobiz | **CORRECTED** | There is **no** Vobiz serializer in Pipecat 1.10.0 — shipped ones are exotel, genesys, plivo, telnyx, twilio, vonage. An earlier draft of this table claimed otherwise; that was wrong. Vobiz's wire protocol is byte-for-byte Plivo's, so we subclass `PlivoFrameSerializer` (§6.1) |
| Pipecat ↔ Sarvam STT streaming | OK | `SarvamSTTService` (saaras:v4) and `SarvamRealtimeSTTService` (saaras:v3-realtime, interim results, VAD tuning) |
| Sarvam code-mixed translation | OK | `mayura:v1`, `mode="code-mixed"` — this *is* the primary/secondary feature |
| Sarvam Indic→Indic | **MEASURED — pivots** | Confirmed by the Phase 0 spike: hi→ta costs the sum of its two hops. Translation alone is ~1.8s, which breaks the original latency budget. See §7.4 |

`playedStream` is more valuable than it looks — it is the only honest source of
"when did the listener actually hear this", and it powers both the feedback-loop
gate (§7.2) and the end-to-end latency metric (§9).

---

## 4. Call flow

### 4.1 Split the call into two phases

**Phase 1 — IVR, in Voice XML.** Menus, DTMF, language selection, room codes.
Server-rendered XML against the Answer/Action URL. Do *not* build this inside
Pipecat. DTMF over a media websocket is fiddly and carrier-specific; `<Gather>`
is a solved problem and gives you retries, timeouts and barge-in on prompts for
free.

**Phase 2 — bridge, in Pipecat.** Once paired, return `<Stream bidirectional>`
and hand the leg to a media worker. The leg stays in the stream for the rest of
the call.

The seam between them is one XML response. Keep it that way.

### 4.2 State machine (per leg)

```
                  ┌─────────────┐
  inbound call ──>│  IDENTIFY   │ look up user by From
                  └──────┬──────┘
                         │ new user
                  ┌──────▼──────────┐
                  │ ASK_LANGUAGES   │ (in English) primary, then secondary
                  └──────┬──────────┘
                         │ saved
       ┌─────────────────▼──────────────────┐
       │              MENU                  │  spoken in primary + secondary
       │  1 create room · 2 dial · 3 join   │
       │  9 change language                 │
       └──┬──────────┬──────────┬───────────┘
          │1         │2         │3
 ┌────────▼───┐ ┌────▼─────┐ ┌──▼───────────┐
 │ROOM_CREATED│ │ASK_NUMBER│ │ASK_ROOM_CODE │
 │ speak code │ │ dial out │ │   <code>#    │
 │ WAIT_PEER  │ └────┬─────┘ └──┬───────────┘
 └────────┬───┘      │          │
          └──────────┴──────────┘
                     │ both legs present
               ┌─────▼─────┐
               │  BRIDGED  │  <Stream bidirectional>
               └───────────┘
```

Outbound leg (someone dialled *by* the AI) skips MENU entirely:
`IDENTIFY → ASK_LANGUAGES (if new) → BRIDGED`.

Model this as an explicit `LegState` StrEnum with a transition table, not as
if/elif scattered across XML handlers. Every transition emits an event (§9) —
that is how you debug "the pairing felt slow" later.

### 4.2b How prompts get spoken (built, Phase 3)

The requirement that menus play in the caller's primary *and* secondary language
means every prompt exists in 11 languages. Three ways to get there, and the
choice is not obvious:

| | cost per call | reviewable |
|---|---|---|
| Vobiz `<Speak>` in-built TTS | free | n/a — limited Indic coverage |
| Translate at call time, cache | first call pays ~1.2s **per prompt** | no |
| **Pre-generate, commit** ✅ | free | yes, it is a diff |

Prompts are static, so translating them at runtime buys nothing and costs
latency on the one call least able to afford it — a first-time caller. They are
generated by `scripts/generate_prompts.py` into `app/ivr/prompts/<lang>.json`
and **committed**, so machine output that ships to users is reviewed in a pull
request rather than materialised where nobody ever reads it.

Two rules that fell out of building it:

- **No placeholders in translated text.** A room code is spoken by *appending*
  digits to a prompt, never by interpolating into it. Machine translation
  reorders and mangles `{code}` markers, and a prompt that reads the marker
  aloud is a dead call.
- **Digits are spaced.** `speak_digits("1282")` → `"1 2 8 2"`, or TTS says "one
  thousand two hundred and eighty-two", which nobody can write down.

Generated text is a starting point, not an authority — the first pass produced a
Hindi menu that mixed formal `कीजिए` with informal `करो` in one sentence.

### 4.3 Language selection over the phone

22 languages do not fit a 0–9 keypad. `<Gather>` supports speech and DTMF
simultaneously, so:

- Prompt: *"Say your language, or press 1 for Hindi, 2 for Tamil…"*
- Speech is the primary path (ASR over a closed set of ~22 language names is
  near-perfect); DTMF covers the top 8 by expected traffic as a fallback.
- Confirm once: *"Hindi. Press 1 to confirm, 2 to change."* Getting this wrong
  poisons every later call for that number.

Secondary language defaults to English and in practice will almost always stay
English — make "press 1 to keep English" the fast path, not a full second menu.

### 4.4 Room codes

- 4 digits, `1000–9999`, allocated via Redis `SET NX` with retry on collision.
- TTL 10 minutes, unbound; extended to call duration once paired.
- One-shot: consumed on join, so a code never pairs three people.
- **Risk:** 4 digits is guessable. Acceptable for v1 given the TTL and
  single-use property, but log every failed join attempt per number and
  rate-limit joins hard (§11). Revisit if this ever goes public.

---

## 5. Component architecture

Layering per `.claude/skills/clean-architecture-patterns`. The non-obvious part
is that the Pipecat pipeline is **infrastructure**, not a service — services
orchestrate it, they do not import frame processors.

```
live-call-translator/
  backend/                      # FastAPI + Pipecat
    .env.local                  # git-ignored, real secrets
    .env.local.example          # committed template
    .env.prod
    .env.prod.example
    app/
      api/
        v1/
          xml/            # Vobiz Answer/Action webhooks -> Voice XML  (thin)
          ws/             # media websocket endpoints                 (thin)
          admin/          # admin REST
          users/          # end-user REST (settings, call history)
      services/
        ivr_service.py          # state machine, owns LegState transitions
        pairing_service.py      # room create/join/dial, peer rendezvous
        call_service.py         # call + leg lifecycle
        language_service.py     # user language prefs, resolution rules
        rate_limit_service.py
        billing_service.py
      repositories/
        interfaces.py           # IUserRepository, ICallRepository, ...
        postgres/               # SQLAlchemy implementations
        redis/                  # IRoomRegistry, ILegLocator (ephemeral state)
      pipeline/                 # Pipecat land
        bridge.py               # builds the 2 pipelines for a paired call
        processors/
          utterance_gate.py     # floor control / feedback suppression (§7.2)
          translation.py        # MT frame processor
          telemetry.py          # emits domain events, no DB access
      providers/                # Strategy: swappable AI vendors
        interfaces.py           # ISpeechToText, ITranslator, ITextToSpeech
        sarvam/
        registry.py             # Factory Method, config-driven
      telephony/
        interfaces.py           # ITelephonyProvider
        vobiz/                  # XML builder, REST client, WS serializer glue
      events/
        bus.py                  # in-process async pub/sub
        subscribers/            # Observer: db_writer, otel, archiver, costing
      models/                   # SQLAlchemy ORM
      schemas/                  # Pydantic DTOs
      core/                     # config, enums, exceptions, logging, constants
      dependencies.py
    scripts/                    # Phase 0 spikes, one-off tools
    tests/{unit,integration}
  frontend/                     # Next.js — admin panel + user portal
    .env.local
    .env.local.example
    .env.prod
    .env.prod.example
    src/{app,components,lib}
  infra/                        # docker-compose, ops
  docs/
```

**Environment files.** Separate files per environment, never one `.env` with
overrides: `.env.local` and `.env.prod` in each of `backend/` and `frontend/`.
Both are git-ignored; `.env.*.example` templates are committed. The backend
picks its file from `APP_ENV` (`local` | `prod`), defaulting to `local`, so
running against prod config is always a deliberate act.

**Patterns actually being used, and why:**

| Pattern | Where | What it buys | What it costs |
|---|---|---|---|
| Strategy | `providers/*` | Swap Sarvam→Deepgram/ElevenLabs per stage when quality demands it; fake providers in tests | One interface per stage |
| Factory Method | `providers/registry.py` | Provider choice lives in config, one branch point | Indirection at construction |
| Repository | `repositories/*` | Services testable without Postgres; Redis vs PG split is invisible upstream | ~2 files per aggregate |
| Observer | `events/*` | Telemetry/archival/costing don't pollute the audio hot path — this is the whole observability layer | Async ordering care |
| State | `ivr_service` | IVR transitions are explicit and loggable | A transition table |
| Chain of Responsibility | `rate_limit_service` | Rules reorder/extend without touching call setup | Small |
| Adapter | `telephony/*` | Vobiz swappable for Plivo/Exotel (Pipecat has serializers for all three) | One interface |

**Deliberately NOT used:** no CQRS, no event sourcing, no DI container beyond
FastAPI `Depends`, no microservices. One backend service + one media worker
role. The complexity budget belongs in the audio path, not the object graph.

---

## 6. The translation pipeline

### 6.1 Transport and serializer (built, Phase 1)

Pipecat 1.10 has no Vobiz serializer. But Vobiz's streaming protocol is Plivo's,
event for event — `media`/`dtmf` inbound, `playAudio`/`clearAudio` outbound, the
same `streamId` envelope and the same base64 mulaw payload. So
`VobizFrameSerializer` subclasses `PlivoFrameSerializer` and overrides exactly
one thing: the hangup REST call, which Pipecat hardcodes to `api.plivo.com`.

Two things this bought us for free:

- **DTMF arrives over the media stream** (`{"event":"dtmf","dtmf":{"digit":...}}`
  → `InputDTMFFrame`). The deferred question about in-call keypresses is
  answered: they work.
- The `start` event's field spelling is undocumented, so `parse_stream_start`
  accepts the plausible variants and the handler logs the raw frame. The first
  real call collapses it to one spelling.

Two non-obvious facts, both learned the hard way and both pinned by tests:

1. **`transport.input() → transport.output()` echoes silence.** Input emits
   `InputAudioRawFrame`; output only writes `OutputAudioRawFrame`. The frames
   traverse the pipeline and are dropped at the end. `AudioLoopback` converts
   between them, and that one processor *is* the echo bot.
2. **The pipeline takes several seconds to start**, and audio pushed before
   `StartFrame` reaches the end of it is discarded.

Everything runs at 8 kHz end to end — Vobiz streams 8 kHz mulaw and Sarvam TTS
emits it directly — so there is no resampling anywhere to blame for jitter.

### 6.2 The bridge

Two Pipecat pipelines per call, one per direction, sharing a `CallSession`.

```python
# direction A → B
Pipeline([
    transport_a.input(),        # Vobiz WS, mulaw 8k -> PCM
    vad_a,                      # Silero
    stt_a,                      # SarvamRealtimeSTTService(lang=A.primary)
    utterance_assembler_a,      # finalize -> Utterance(seq, text)
    translator_a2b,             # Mayura A.primary -> B.primary, mode by B.secondary
    tts_b,                      # Bulbul, voice for B.primary
    playout_queue_b,            # strict seq ordering (§7.3)
    transport_b.output(),       # Vobiz WS for leg B
])
```

Note `transport_a.input()` and `transport_b.output()` in the *same* pipeline.
That is the bridge. Pipecat allows it; the transports just need independent
lifecycles.

The mirrored pipeline runs B→A. They share:
- `CallSession` — ids, languages, per-direction sequence counters
- the event bus

**Do not** put the two directions in a `ParallelPipeline`. They are independent
pipelines that happen to share state; coupling their frame lifecycles creates
head-of-line blocking between speakers.

---

## 7. The hard problems

These are the project. Everything else is CRUD.

### 7.1 Utterance boundary detection

The user-visible quality metric is "did it wait too long, or did it cut me off",
and both come from here.

Layered detection, cheapest first:
1. **Silero VAD** — `stop_secs` tuned per language. Start at 0.7s. This is the
   single biggest latency lever; every 100ms here is 100ms of dead air.
2. **STT endpointing** — `SarvamRealtimeSTTService` exposes VAD params and
   interim transcripts. Its final-transcript signal is usually better than raw
   VAD because it is acoustic *and* linguistic.
3. **Punctuation / clause boundary** on interim text — if the interim ends in
   `।?!.` and 300ms of silence follows, finalize early.
4. **Hard ceiling** — force-finalize at 12s of continuous speech so a monologue
   streams out in chunks instead of landing as one 40-second block.

Phase 8 optimization: **clause-level streaming**. Translate and speak each
clause as it completes rather than waiting for the full utterance. Roughly
halves perceived latency on long sentences. Deliberately deferred — it makes
ordering and floor control much harder, and the naive version must work first.

### 7.2 Acoustic feedback — DEFERRED

**Decision: out of scope for v1.** We assume the two parties are acoustically
separated — different rooms, different places, or headsets — so neither phone's
speaker reaches the other's mic.

Recorded here so the assumption stays visible rather than becoming folklore. If
the two phones *can* hear each other, translated audio played to B is picked up
by A's mic, transcribed as if A said it, translated back, and the call
degenerates into a loop. Nothing downstream fixes it after the fact.

When this needs solving, the seam is already in the design: `playout_queue`
knows exactly when audio starts and stops playing on a leg (via Vobiz
`checkpoint`/`playedStream`, §7.3), so a half-duplex input gate hangs off that
one place. Two supporting mitigations, if it ever comes up:

- A one-time IVR line suggesting earphones for first-time users.
- A rolling hash of recent translated outputs per call; drop an inbound
  transcript that matches one.

Do not build any of this now. Validate the assumption by testing with the two
phones in different rooms.

### 7.3 Ordering and no-loss delivery

"No barge-in, everything is transmitted" means the playout side is a queue, not
a stream.

- Every utterance gets `(direction, seq)` at finalization.
- `playout_queue_b` releases audio strictly in `seq` order per direction. A slow
  translation for seq 5 blocks seq 6 rather than reordering the conversation.
- Use Vobiz `checkpoint`/`playedStream` per utterance for real playback
  accounting. Never infer completion from audio byte counts.
- Never call `clearAudio` in v1 — that is barge-in, which is out of scope.
- Backpressure: if a direction's queue exceeds ~20s of pending audio the speaker
  is far ahead of the listener. Log a `PlayoutBacklog` event and surface it in
  the admin panel; do not silently drop.

### 7.4 Translation fidelity

The stated requirement — *pure translation, preserve broken grammar, don't
"fix" intent* — fights the natural behaviour of translation models, which
normalize and tidy.

- `mayura:v1` with `mode="code-mixed"` when the user has a secondary language
  set, `mode="modern-colloquial"` otherwise. Code-mixed mode is precisely the
  Hinglish behaviour described in the requirements — it is a parameter, not a
  feature to build.
- `enable_preprocessing=False` by default; it normalizes, and normalizing is
  exactly what you don't want.
### 7.4.1 Phase 0 spike results (measured)

`scripts/spike_translation.py`, 15 calls per pair, `mode=code-mixed`.

Run twice. The first run used romanised Hindi for every pair, so `ta→hi` and
`te→hi` were fed Hindi text and told it was Tamil/Telugu — they returned
byte-identical output, which is the tell. The corpus is now native-script per
source language. Numbers below are from the corrected run.

| pair | p50 | worst |
|---|---|---|
| hi→en | 709 ms | 829 ms |
| en→ta | 1183 ms | 1356 ms |
| hi→ta | 1889 ms | 2149 ms |
| ta→hi | 1770 ms | 1863 ms |
| te→hi | 1766 ms | 1931 ms |

**Finding 1 — the pivot is confirmed, arithmetically.** hi→en (709) + en→ta
(1183) = 1892 ms, against a measured hi→ta of 1889 ms. Within 0.2%, and the
first run reproduced the same identity on a different corpus. Indic→Indic is two
sequential hops through English and we pay for both.

**Finding 2 — code-mixing works well.** English technical nouns survive into
native script exactly as the requirement wants: ஸ்டேஷன், பேட்டரி, சார்ஜர்,
ஏடிஎம், நியரெஸ்ட் / नियरेस्ट, कैश, विद्ड्रॉ. This part of the design needs no
further work.

**Finding 3 — quality is good, with one repeatable failure mode.** On
native-script input, translations are faithful and colloquial, and the address
term usually survives: Tamil `அண்ணே` → Hindi `ब्रदर`. Three defects, all worth
tracking in the Phase 2 eval rather than blocking on:

- **Disjunctive questions get mangled.** "is this hotel good, or should I look
  at another?" came back in Tamil as *"are you asking whether to check out
  another one?"* — a question about the question. The same construction
  degraded into awkward Hindi on ta→hi. This is the one real intent distortion,
  and it reproduced across pairs.
- **Honorific polarity flips.** Hindi `भाई` (elder-brother address) became Tamil
  `தம்பி`, which means *younger* brother. Seniority inverted — socially wrong in
  exactly the setting this product is for.
- **Mild intensity drift.** Telugu "battery has gone low" became Hindi "battery
  is dead".

The first, invalid run showed far worse embellishment (a bare "can I get a
charger?" became "could you please provide a charger for this?"). That now looks
like an artefact of feeding the model mislabelled text, not Mayura's normal
behaviour — a useful reminder that a bad corpus makes a model look worse than it
is.

### 7.4.1b Mode A/B (Phase 2 eval harness)

`scripts/eval_translation.py --variants code-mixed,formal,modern-colloquial`.
Latency is identical across modes (p50 1707 / 1740 ms), so this is purely a
quality choice.

**The two colloquial modes are near-identical in output. `formal` is the
genuinely different one, and it trades one class of bug for a worse one.**

| | `code-mixed` / `modern-colloquial` | `formal` |
|---|---|---|
| English loan words | **preserved** — ஸ்டேஷன், பேட்டரி, கேஷ் | **nativised** |
| Disjunctive questions | **broken** (see below) | correct |
| Register | casual, matches the speaker | stiff |

The decisive case: `भाई मुझे स्टेशन जाना है` ("I need to go to the station").

- `code-mixed` → `ஸ்டேஷன்` ✅
- `formal` → **`காவல் நிலையம்`** ❌ — *police station*. It "translated" the
  loan word and invented a meaning the speaker never had.

That is a far worse failure than clumsy phrasing, and it is exactly the kind of
error that matters when a traveller is asking for directions. **`code-mixed`
stays the default, and `formal` is not a fallback.**

Two defects confirmed as properties of the *colloquial* modes generally, not of
code-mixing — so switching mode will not fix them:

1. **Disjunctive questions collapse.** "is this hotel good, or should I look at
   another?" → *"are you asking whether to check out another one?"*
2. **Leading interrogatives get dropped.** "Where is the nearest ATM machine, I
   need to withdraw cash urgently" → roughly *"I must have gone to the ATM
   machine, need cash urgently"*. The question disappears entirely.

Both are worth a dedicated attempt in Phase 8, and both are now pinned as rows
in `eval/dataset.jsonl` so any future change is measured against them rather
than argued about. The likely fix is not a Sarvam parameter — it is an LLM
translator with an explicit "preserve sentence type" instruction, benchmarked on
this same dataset.

### 7.4.2 What this does to the latency budget

Translation alone is ~1.8s against a 2s end-to-end p95 target. The target does
not survive contact with this, and the brief says to get the pipeline working
first — so v1 ships at ~3s and §9 records the real numbers. Levers, cheapest
first, all Phase 8:

1. **Collapse the first hop into STT.** Sarvam's `speech-to-text-translate`
   (Saaras) emits English text directly from source-language audio. Since we
   already pay for an STT call, the hi→en hop becomes free and only en→target
   remains — roughly 650 ms off, for no extra request. This is the single
   biggest win available and should be the first thing tried.
2. **Clause-level streaming** (§7.1) — overlaps translation with speech rather
   than making it shorter.
3. An LLM translator, streamed, if it beats Mayura on the eval *and* on latency.

Do not do any of these before Phase 4. A slow call that works beats a fast one
that does not exist.
- **Build a translation eval harness in Phase 2, not at the end.** ~100 recorded
  utterances across 5 language pairs with reference translations; score with
  chrF++/COMET plus a human 1–5 on register preservation. Without this, "quality
  first" is a vibe, and you cannot tell whether swapping a provider helped.

---

## 8. Data model

Postgres + SQLAlchemy 2.0 (async) + Alembic. Ephemeral state (rooms, leg
locations, rate counters) lives in Redis and is never written to Postgres.

```
users            id, phone_e164 (uniq), primary_lang, secondary_lang,
                 plan, created_at, last_call_at

rooms            id, code (uniq active), creator_leg_id, status, expires_at
                 -- mirrored in Redis for the hot path; PG row is the audit record

calls            id, room_id, initiator_user_id, pairing_mode, status,
                 started_at, bridged_at, ended_at, end_reason, worker_id

call_legs        id, call_id, user_id, provider_call_uuid, direction(IN|OUT),
                 phone_e164, language_primary, language_secondary,
                 state, answered_at, ended_at, hangup_cause, recording_url

utterances       id, call_id, from_leg_id, to_leg_id, seq,
                 src_lang, dst_lang, stt_text, stt_confidence, mt_text,
                 mode_used, provider_stt, provider_mt, provider_tts,
                 audio_src_url, audio_tts_url,
                 -- timings, all epoch ms, this is the latency table
                 speech_start_ts, speech_end_ts, stt_first_partial_ts,
                 stt_final_ts, mt_start_ts, mt_end_ts, tts_first_byte_ts,
                 tts_complete_ts, playout_start_ts, playout_done_ts,
                 dropped_reason
                 -- derived: e2e_latency_ms = playout_start_ts - speech_end_ts

ivr_events       id, leg_id, from_state, to_state, dtmf, asr_text, at

usage_ledger     id, user_id, call_id, provider, unit, qty, unit_cost_paise,
                 total_paise, at

rate_limit_rules  -- config-file backed; table only for admin overrides
blacklist        phone_e164, reason, at
```

`utterances` is the observability spine. Index `(call_id, seq)` and
`(created_at)`; it will be the largest table by far. Partition by month once
volume justifies it, not before.

---

## 9. Observability

Design goal from the requirements: *inspect every call, and within a call every
sentence's pipeline, to judge quality.*

**Emission — Observer pattern, strictly off the hot path.** Frame processors
publish domain events to an in-process async bus; they never touch the DB, S3 or
OTel directly. A slow subscriber must not add latency to audio.

```
UtteranceFinalized / TranslationCompleted / PlayoutStarted / PlayoutCompleted
/ LegStateChanged / ProviderCallCompleted / ProviderError
        │
        ├─> DbUtteranceWriter     batched upserts into utterances
        ├─> OtelSpanEmitter       one trace per utterance, span per stage
        ├─> AudioArchiver         source + TTS clips -> S3/MinIO (async)
        ├─> CostAccountant        usage_ledger rows
        └─> MetricsCollector      Prometheus histograms
```

**Tracing.** Pipecat has built-in OpenTelemetry support — use it. One trace per
utterance, `call_id` and `leg_id` as span attributes. Stage spans: `vad`, `stt`,
`mt`, `tts`, `playout`. This makes "where did the 2 seconds go" a single
waterfall view rather than a log-grepping exercise.

**The call inspector** (admin panel's most important screen): a call timeline
with both legs as parallel tracks, each utterance a block showing source audio,
transcript, translation, synthesized audio, the full timing waterfall, and cost.
Build this in Phase 5 — it is what makes every later quality problem debuggable.

**Latency budget**, p95 target 2s, measured `speech_end_ts → playout_start_ts`:

| Stage | Budget | Notes |
|---|---|---|
| Endpoint detection | 500–700 ms | dominant tunable; the `stop_secs` knob |
| STT finalization | 150–350 ms | mostly overlapped via streaming |
| Translation | **~1800 ms** | **measured**, not budgeted — Indic→Indic pivots (§7.4.1) |
| TTS first byte | 150–400 ms | stream, don't wait for full audio |
| Network + jitter | 100–200 ms | |
| **Total** | **~2.7–3.45 s** | over target, accepted for v1 |

The 2s p95 target does not survive the measured translation cost. v1 ships at
~3s deliberately: the brief prioritises a working pipeline over a fast one, and
the §7.4.2 levers (Saaras collapsing the first hop, then clause streaming) are
Phase 8 work that only makes sense once there is a call to measure.

**Cost model** (fill from live vendor pricing in Phase 0; target ≤ ₹10/min):

```
per conversation-minute = 2 × telephony_leg  +  2 × STT_min
                        + 2 × MT_chars       +  2 × TTS_chars
```

Track actuals in `usage_ledger` from day one and put cost-per-minute on the
admin dashboard. If it comes in over budget, the cheapest lever is TTS voice
tier, not STT quality.

---

## 10. Scale — DEFERRED

**Decision: v1 targets one successful call on one process.** Single FastAPI
process serving both the Voice XML webhooks and the media websockets. No worker
pool, no sticky routing, no load balancer.

Two cheap habits keep the door open without costing anything now:

1. **Keep ephemeral pairing state in Redis, not in a Python dict.** Room codes
   and leg locations go through `IRoomRegistry` from day one. Same amount of
   code, and it is the one thing that would be painful to retrofit.
2. **Keep the webhook handlers stateless.** They already have to be — Vobiz
   calls them per-event, not per-connection.

When this needs solving, the shape is: split the control plane (stateless,
webhooks + REST) from the media plane (stateful, holds websockets and
pipelines); record `room_code → worker_url` in Redis at leg creation; and point
the second leg's `<Stream>` XML at that specific worker. Rendezvous happens
before any media flows, which is when redirection is free. Do **not** forward
audio between workers — that puts a network hop inside the latency budget.

Rough sizing for whenever that day comes: the constraint is CPU, not
connections — VAD, resampling and codec work run roughly 0.1–0.2 vCPU per active
leg. Measure before provisioning anything.

---

## 11. Rate limiting & config

Chain of Responsibility, evaluated at leg setup, before any AI provider is
touched:

```
BlacklistRule → PremiumBypassRule → DailyCallCapRule
  → DailyMinutesCapRule → ConcurrentCallsRule → ALLOW
```

Each rule returns allow / deny-with-reason. Denials map to a configured spoken
message in the caller's primary language, then hangup.

`config/limits.yaml`, hot-reloadable, Pydantic-validated:

```yaml
defaults:
  max_calls_per_day: 20
  max_minutes_per_day: 60
  max_concurrent_calls_per_number: 1
  max_room_join_attempts_per_hour: 10
premium_numbers: ["+9198XXXXXXXX"]      # bypass all limits
blacklist:
  - number: "+9199XXXXXXXX"
    reason: "abuse"
messages:
  rate_limited: "You have reached your daily limit. Please try again tomorrow."
  blacklisted: "This number is not permitted to use this service."
  room_not_found: "That room code was not found. Please try again."
```

Counters in Redis with day-boundary TTLs in IST. Every denial emits an event and
shows up in the admin panel — silent throttling is how you lose a day debugging
"the number just hangs up".

---

## 12. Admin panel & user portal (Next.js)

**Auth:** phone number → session, no OTP in v1. `ADMIN_BYPASS_TOKEN` env var for
admin login. **Risk:** anyone who knows a phone number can read that user's call
transcripts. That is fine for a private side project and **must not ship
publicly without OTP** — noted here so the decision stays deliberate.

**Admin:** live calls dashboard (active legs, states, latency); call list with
filters; **call inspector** (§9); users; usage & cost; errors & provider health;
config editor for limits/blacklist; health checks.

**User portal:** call history with transcripts, language settings, plan & usage.

---

## 13. Phased roadmap

Each phase has a demo that either works or doesn't. No phase is "infrastructure
only".

| Phase | Deliverable | Done when |
|---|---|---|
| **0. Spikes & skeleton** ✅ | Repo skeleton, docker-compose, config, provider layer. Translation spike run twice (§7.4.1) | **Done.** Latency and quality measured; pivot confirmed. Cost model still unfilled |
| **1. Media path** ✅ | `<Stream bidirectional>` XML, media websocket, `VobizFrameSerializer`, echo bot | **Done and confirmed on a real call** — own voice returned, clear, no jitter |
| **2. Single-leg translation** ~ | STT→MT→TTS on one leg via `PipelineMode.TRANSLATE_LOOPBACK`; `TranslationProcessor`; eval harness + dataset | **Code done, tests green, mode A/B run (§7.4.1b).** **Not yet confirmed on a real call** |
| **3. IVR** ~ | `IvrService` state machine, `<Gather>`, language selection, room create/join/dial-out, Postgres (users/calls/legs + Alembic), Redis room registry, generated prompt catalog | **Code done, 45 tests green** including two callers pairing by room code against real Postgres + Redis. **Not yet confirmed on a real call**, and dial-out has never been exercised against the live Vobiz API |
| **4. The bridge** | Two-leg cross-transport pipelines, strict `seq` ordering queue | **Two phones in different rooms hold a real translated conversation.** Translated voice only, no double audio |
| **5. Observability** | Event bus + subscribers, `utterances` table, OTel, audio archival | Every utterance inspectable end-to-end with a timing waterfall |
| **6. Admin panel** | Next.js, phone login, call inspector, dashboards | You debug a real quality complaint using only the panel |
| **7. Limits & billing** | Rate limit chain, config, usage ledger, plans | A capped number hears the right message in its own language |
| **8. Latency** | Clause-level streaming, `stop_secs` tuning | p95 ≤ 2s measured on real calls |

**Phase 4 is the finish line for v1** — one successful translated call between
two people. Phases 5–8 are what turn it into a product.

---

## 14. Open questions

1. **Sarvam Indic↔Indic** — direct or pivoted through English? Decides whether
   the latency budget holds. *Resolve in Phase 0.*
2. ~~**Vobiz max stream duration**~~ — **resolved.** `<Stream streamTimeout>`
   defaults to 86400s and `maxRetries` (0–10) covers reconnects. We set 3600s
   and `keepCallAlive="true"`, without which the call ends the moment the
   stream is established.
3. **Vobiz capacity** — concurrency/CPS is purchased via
   `channel-subscriptions`. Buy the minimum; revisit only if v1 works.
4. **Recording consent** — storing per-utterance audio of both parties has legal
   weight in India. Add a spoken disclosure at call start and a retention policy
   (suggest 30 days) before any real users.
5. **TTS voice per language** — Bulbul voice selection per target language needs
   a curated map; default voice quality varies across Indic languages.

---

## 15. Where I'd push back

- **4-digit room codes** are guessable. Fine for a private project with a 10-min
  TTL and single-use codes; not fine if this goes public.
- **Phone-number-only login** exposes transcripts to anyone who knows a number.
  Deliberate v1 trade-off, flagged in §12.
- **The deferred echo assumption (§7.2) is a real constraint on demoing this.**
  The motivating story — standing next to someone in Chennai — is exactly the
  case v1 does not handle. Test in different rooms, and know that "two phones on
  one table" will fail until the gate in §7.2 gets built.

---

## Sources

- [Vobiz — WebSockets & Streaming](https://vobiz.ai/docs/concepts/streaming-websockets)
- [Vobiz — Stream (Voice XML)](https://vobiz.ai/docs/xml/stream)
- [Vobiz — Gather (DTMF + Speech)](https://vobiz.ai/docs/xml/gather)
- [Vobiz — Make an Outbound Call](https://vobiz.ai/docs/call/make-call)
- [Vobiz — Pipecat integration](https://vobiz.ai/docs/integrations/pipecat)
- [Vobiz-Pipecat reference repo](https://github.com/vobiz-ai/Vobiz-Pipecat)
- [Pipecat — Sarvam STT service](https://docs.pipecat.ai/server/services/stt/sarvam)
- [Sarvam — Mayura translation model](https://docs.sarvam.ai/api-reference-docs/models/mayura)
- [Sarvam — Realtime streaming STT](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming)
- [Sarvam — Streaming TTS](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/streaming-api/web-socket)
