"""Phase 2 translation eval harness.

Two jobs, and it is honest about which is which:

1. **A/B a configuration change.** Run the same dataset through two or more
   variants (mode, model) and print the outputs side by side with latency. No
   reference translations needed - this is the question "did changing `mode`
   make it better?", which a human answers by reading.

2. **Score against references, once you have them.** Every row in the dataset
   starts with `"reference": null`, because writing a reference translation is
   human work and inventing them would make this harness lie. Fill some in and
   the script starts reporting chrF for those rows, so a later change can be
   caught as a regression rather than an opinion.

Usage:
    cd backend
    uv run python scripts/eval_translation.py
    uv run python scripts/eval_translation.py --variants code-mixed,formal
    uv run python scripts/eval_translation.py --json eval-run.json
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
from app.providers.interfaces import ITranslator  # noqa: E402
from app.providers.registry import build_providers  # noqa: E402
from app.schemas.translation import TranslationRequest  # noqa: E402

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "eval" / "dataset.jsonl"


@dataclass(frozen=True, slots=True)
class EvalCase:
    id: str
    source_language: Language
    target_language: Language
    text: str
    reference: str | None
    note: str | None


@dataclass(slots=True)
class CaseResult:
    case: EvalCase
    variant: str
    output: str | None
    latency_ms: float | None
    error: str | None = None
    chrf: float | None = None


@dataclass(slots=True)
class VariantSummary:
    name: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def latencies(self) -> list[float]:
        return [r.latency_ms for r in self.results if r.latency_ms is not None]

    @property
    def p50(self) -> float:
        return statistics.median(self.latencies) if self.latencies else float("nan")

    @property
    def scored(self) -> list[float]:
        return [r.chrf for r in self.results if r.chrf is not None]


def load_dataset(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_number}: invalid JSON - {exc}") from exc
        cases.append(
            EvalCase(
                id=row["id"],
                source_language=Language(row["source_language"]),
                target_language=Language(row["target_language"]),
                text=row["text"],
                reference=row.get("reference"),
                note=row.get("note"),
            )
        )
    return cases


def chrf(hypothesis: str, reference: str, *, n: int = 6, beta: float = 2.0) -> float:
    """Character n-gram F-score, the standard metric for morphologically rich
    languages - word-level BLEU is close to useless for Tamil or Telugu.

    Implemented here rather than pulled from sacrebleu to keep the eval
    dependency-free; it matches chrF (not chrF++, which adds word n-grams).
    """
    precisions: list[float] = []
    recalls: list[float] = []

    for order in range(1, n + 1):
        hyp_grams = _char_ngrams(hypothesis, order)
        ref_grams = _char_ngrams(reference, order)
        if not hyp_grams or not ref_grams:
            continue

        overlap = sum(min(count, ref_grams.get(gram, 0)) for gram, count in hyp_grams.items())
        precisions.append(overlap / sum(hyp_grams.values()))
        recalls.append(overlap / sum(ref_grams.values()))

    if not precisions:
        return 0.0

    avg_precision = sum(precisions) / len(precisions)
    avg_recall = sum(recalls) / len(recalls)
    if avg_precision + avg_recall == 0:
        return 0.0

    beta_sq = beta * beta
    return 100 * (1 + beta_sq) * avg_precision * avg_recall / (beta_sq * avg_precision + avg_recall)


def _char_ngrams(text: str, order: int) -> dict[str, int]:
    stripped = "".join(text.split())
    counts: dict[str, int] = {}
    for i in range(len(stripped) - order + 1):
        gram = stripped[i : i + order]
        counts[gram] = counts.get(gram, 0) + 1
    return counts


async def run_variant(
    translator: ITranslator,
    cases: list[EvalCase],
    mode: TranslationMode,
) -> VariantSummary:
    summary = VariantSummary(name=mode.value)

    for case in cases:
        try:
            result = await translator.translate(
                TranslationRequest(
                    text=case.text,
                    source_language=case.source_language,
                    target_language=case.target_language,
                    mode=mode,
                )
            )
        except AppError as exc:
            summary.results.append(
                CaseResult(
                    case=case, variant=mode.value, output=None, latency_ms=None, error=str(exc)
                )
            )
            continue

        summary.results.append(
            CaseResult(
                case=case,
                variant=mode.value,
                output=result.text,
                latency_ms=result.latency_ms,
                chrf=chrf(result.text, case.reference) if case.reference else None,
            )
        )

    return summary


def print_report(summaries: list[VariantSummary], cases: list[EvalCase]) -> None:
    print("\n=== Latency by variant ===")
    print(f"{'variant':<20}{'n':>5}{'p50 ms':>10}{'errors':>9}")
    for s in summaries:
        errors = sum(1 for r in s.results if r.error)
        print(f"{s.name:<20}{len(s.results):>5}{s.p50:>10.0f}{errors:>9}")

    scored = [s for s in summaries if s.scored]
    if scored:
        print("\n=== chrF against references ===")
        for s in scored:
            mean = sum(s.scored) / len(s.scored)
            print(f"{s.name:<20}{len(s.scored):>4} scored   mean chrF {mean:6.1f}")
    else:
        print("\n=== chrF ===")
        print("No references in the dataset yet, so nothing is scored.")
        print('Fill in some "reference" fields in eval/dataset.jsonl to enable this.')

    print("\n=== Outputs, side by side ===")
    by_case: dict[str, dict[str, CaseResult]] = {}
    for s in summaries:
        for r in s.results:
            by_case.setdefault(r.case.id, {})[s.name] = r

    for case in cases:
        print(f"\n--- {case.id}  ({case.source_language.value} -> {case.target_language.value})")
        if case.note:
            print(f"    note: {case.note}")
        print(f"    in : {case.text}")
        for variant_name, result in by_case.get(case.id, {}).items():
            rendered = result.error or result.output or ""
            score = f"  [chrF {result.chrf:.1f}]" if result.chrf is not None else ""
            print(f"    {variant_name:<16}: {rendered}{score}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--variants",
        default=TranslationMode.CODE_MIXED.value,
        help="comma-separated Sarvam modes to compare, e.g. code-mixed,formal",
    )
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    try:
        modes = [TranslationMode(v.strip()) for v in args.variants.split(",") if v.strip()]
    except ValueError as exc:
        raise SystemExit(
            f"{exc}. Valid modes: {', '.join(m.value for m in TranslationMode)}"
        ) from exc

    cases = load_dataset(args.dataset)
    if not cases:
        raise SystemExit(f"no cases in {args.dataset}")

    providers = build_providers(get_settings())
    try:
        summaries = [await run_variant(providers.translator, cases, mode) for mode in modes]
    finally:
        await providers.aclose()

    print_report(summaries, cases)

    if args.json:
        args.json.write_text(
            json.dumps(
                [
                    {
                        "variant": s.name,
                        "p50_ms": s.p50,
                        "results": [
                            {
                                "id": r.case.id,
                                "source_language": r.case.source_language.value,
                                "target_language": r.case.target_language.value,
                                "input": r.case.text,
                                "output": r.output,
                                "latency_ms": r.latency_ms,
                                "chrf": r.chrf,
                                "error": r.error,
                            }
                            for r in s.results
                        ],
                    }
                    for s in summaries
                ],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {args.json}")

    return 1 if any(r.error for s in summaries for r in s.results) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
