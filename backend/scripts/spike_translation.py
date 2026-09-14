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

#: One corpus per source language, in that language's own script.
#:
#: The first run of this spike used romanised Hindi for every pair, so ta->hi and
#: te->hi were handed Hindi text and told it was Tamil/Telugu. They returned
#: byte-identical output, which is the tell. Latency was still measurable, but
#: the quality verdict on those pairs was worthless. Source text must actually
#: be in the source language.
#:
#: Each corpus deliberately mixes English technical nouns with casual, slightly
#: broken grammar - the two things the requirements say must survive.
CORPUS: dict[Language, list[str]] = {
    Language.HINDI: [
        "भाई मुझे स्टेशन जाना है, कितना टाइम लगेगा?",
        "मेरे फ़ोन की बैटरी लो हो गई है, चार्जर मिलेगा क्या?",
        "यह वाला होटल अच्छा है क्या, या मैं दूसरा देखूँ?",
        "मुझे अर्जेंट कैश निकालना है, नियरेस्ट ATM कहाँ है?",
    ],
    Language.TAMIL: [
        "அண்ணே எனக்கு ஸ்டேஷன் போகணும், எவ்வளவு டைம் ஆகும்?",
        "என் ஃபோன் பேட்டரி லோ ஆயிடுச்சு, சார்ஜர் கிடைக்குமா?",
        "இந்த ஹோட்டல் நல்லா இருக்கா, இல்ல வேற பாக்கவா?",
        "எனக்கு அர்ஜென்ட்டா கேஷ் வேணும், பக்கத்துல ATM எங்க இருக்கு?",
    ],
    Language.TELUGU: [
        "అన్నా నాకు స్టేషన్ కి వెళ్ళాలి, ఎంత టైమ్ పడుతుంది?",
        "నా ఫోన్ బ్యాటరీ లో అయిపోయింది, ఛార్జర్ దొరుకుతుందా?",
        "ఈ హోటల్ బాగుందా, లేక వేరే చూడాలా?",
        "నాకు అర్జెంట్ గా క్యాష్ కావాలి, దగ్గరలో ATM ఎక్కడ ఉంది?",
    ],
    Language.ENGLISH: [
        "Bro how much time it will take to reach the station?",
        "My phone battery is low, can I get a charger?",
        "Is this hotel good or should I check another one?",
        "Where is the nearest ATM machine, I need to withdraw cash urgently",
    ],
}

#: en<->Indic pairs establish the per-hop baseline; the Indic<->Indic pairs are
#: the ones suspected of paying for two hops.
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

    for text in CORPUS[source]:
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
        print("(approximate: each source language now has its own corpus, so")
        print(" input lengths differ slightly between pairs)")
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
