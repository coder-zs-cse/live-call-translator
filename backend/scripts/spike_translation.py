"""Phase 0 spike: is Sarvam translation good enough, and fast enough?

Answers the two questions that can invalidate the design before any code is
worth writing (docs/PLAN.md section 7.4):

  1. Does Mayura serve Indic -> Indic directly, or pivot through English?
     A pivot roughly doubles this stage's share of the 2s latency budget. The
     tell is latency: if hi->ta costs about twice hi->en, suspect a pivot.
  2. Does code-mixed mode actually preserve English technical nouns, and does
     translation preserve a speaker's broken grammar rather than tidying it?
     Question 2 needs your eyes, not an assertion - the output is printed for
     you to read.

Usage:
    cd backend
    uv run python scripts/spike_translation.py
    uv run python scripts/spike_translation.py --repeat 5 --json out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.enums import Language, TranslationMode  # noqa: E402
from app.core.exceptions import AppError  # noqa: E402
from app.providers.registry import build_providers  # noqa: E402
from app.schemas.translation import TranslationRequest  # noqa: E402

#: Deliberately includes broken grammar and English technical nouns, because
#: those are the two things the requirements say must survive translation.
SAMPLES: list[str] = [
    "Bhai mujhe station jaana hai, kitna time lagega?",
    "My phone ka battery low ho gaya hai, charger milega kya?",
    "Where is the nearest ATM machine, I need to withdraw cash urgently",
    "Yeh wala hotel accha hai kya, ya main dusra dekhu?",
    "I am not from here, please can you help me finding this address",
]

#: en<->Indic pairs establish the baseline cost; the Indic<->Indic pairs are the
#: ones under suspicion.
PAIRS: list[tuple[Language, Language]] = [
    (Language.HINDI, Language.ENGLISH),
    (Language.ENGLISH, Language.TAMIL),
    (Language.HINDI, Language.TAMIL),
    (Language.TAMIL, Language.HINDI),
    (Language.TELUGU, Language.HINDI),
]


@dataclass(slots=True)
class PairOutcome:
    source: str
    target: str
    latencies_ms: list[float] = field(default_factory=list)
    samples: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def p50(self) -> float:
        return statistics.median(self.latencies_ms) if self.latencies_ms else float("nan")

    @property
    def worst(self) -> float:
        return max(self.latencies_ms) if self.latencies_ms else float("nan")


async def run_pair(
    translator: object,
    source: Language,
    target: Language,
    repeat: int,
) -> PairOutcome:
    outcome = PairOutcome(source=source.value, target=target.value)

    for text in SAMPLES:
        for attempt in range(repeat):
            request = TranslationRequest(
                text=text,
                source_language=source,
                target_language=target,
                mode=TranslationMode.CODE_MIXED,
            )
            try:
                result = await translator.translate(request)  # type: ignore[attr-defined]
            except AppError as exc:
                outcome.errors.append(f"{text[:32]}... -> {exc}")
                break

            outcome.latencies_ms.append(result.latency_ms)
            # Only keep the first rendering; repeats exist to measure latency.
            if attempt == 0:
                outcome.samples.append({"input": text, "output": result.text})

    return outcome


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3, help="calls per sample, for latency")
    parser.add_argument("--json", type=Path, default=None, help="write raw results here")
    args = parser.parse_args()

    settings = get_settings()
    providers = build_providers(settings)

    try:
        outcomes = [
            await run_pair(providers.translator, source, target, args.repeat)
            for source, target in PAIRS
        ]
    finally:
        await providers.aclose()

    print("\n=== Latency by pair ===")
    print(f"{'pair':<16}{'n':>5}{'p50 ms':>10}{'worst ms':>11}  errors")
    for o in outcomes:
        label = f"{o.source}->{o.target}"
        print(f"{label:<16}{len(o.latencies_ms):>5}{o.p50:>10.0f}{o.worst:>11.0f}  {len(o.errors)}")

    baseline = next((o for o in outcomes if o.target == Language.ENGLISH.value), None)
    indic = [
        o
        for o in outcomes
        if o.source != Language.ENGLISH.value and o.target != Language.ENGLISH.value
    ]
    if baseline and indic and baseline.latencies_ms:
        print("\n=== Pivot check ===")
        print(f"en-baseline p50: {baseline.p50:.0f} ms")
        for o in indic:
            if not o.latencies_ms:
                continue
            ratio = o.p50 / baseline.p50
            verdict = "likely pivots via English" if ratio > 1.6 else "looks direct"
            print(f"  {o.source}->{o.target}: {ratio:.2f}x baseline  ->  {verdict}")

    print("\n=== Read these yourself ===")
    print("Did English technical nouns survive? Did broken grammar survive?\n")
    for o in outcomes:
        if not o.samples:
            continue
        print(f"--- {o.source} -> {o.target} ---")
        for s in o.samples[:3]:
            print(f"  in : {s['input']}")
            print(f"  out: {s['output']}")
        print()

    for o in outcomes:
        for err in o.errors:
            print(f"ERROR {o.source}->{o.target}: {err}", file=sys.stderr)

    if args.json:
        args.json.write_text(
            json.dumps(
                [
                    {
                        "source": o.source,
                        "target": o.target,
                        "p50_ms": o.p50,
                        "worst_ms": o.worst,
                        "latencies_ms": o.latencies_ms,
                        "samples": o.samples,
                        "errors": o.errors,
                    }
                    for o in outcomes
                ],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"wrote {args.json}")

    return 1 if any(o.errors for o in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
