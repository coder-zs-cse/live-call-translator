"""Translate the IVR prompt catalog into every supported language.

Output goes to `app/ivr/prompts/<language>.json`, which is **committed**. That
is the point: prompts are static, so translating them at call time would add
latency and cost to every single call for no benefit, and machine output that
ships to users should be reviewable in a diff rather than materialised at
runtime where nobody ever reads it.

The generated files are a starting point, not an authority. Read them, fix what
sounds wrong, and commit the fix - the script never overwrites a language
unless asked, so hand edits survive.

Usage:
    cd backend
    uv run python scripts/generate_prompts.py                  # missing only
    uv run python scripts/generate_prompts.py --overwrite       # regenerate all
    uv run python scripts/generate_prompts.py --languages hi-IN,ta-IN
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.enums import Language, TranslationMode  # noqa: E402
from app.core.exceptions import AppError  # noqa: E402
from app.ivr.catalog import ENGLISH_PROMPTS, PromptKey  # noqa: E402
from app.ivr.prompt_service import PROMPTS_DIR  # noqa: E402
from app.providers.interfaces import ITranslator  # noqa: E402
from app.providers.registry import build_providers  # noqa: E402
from app.schemas.translation import TranslationRequest  # noqa: E402

#: IVR prompts are instructions, not conversation. MODERN_COLLOQUIAL keeps them
#: approachable without the loan-word nativisation that makes FORMAL dangerous
#: (it once rendered "station" as "police station" - see PLAN 7.4.1b).
PROMPT_MODE = TranslationMode.MODERN_COLLOQUIAL

#: Sarvam is fine with parallel requests and 15 prompts x 10 languages is slow
#: in series. Bounded so a rate limit does not turn into 150 failures.
MAX_CONCURRENCY = 2


async def translate_prompt(
    translator: ITranslator,
    key: PromptKey,
    text: str,
    target: Language,
    semaphore: asyncio.Semaphore,
) -> tuple[PromptKey, str | None]:
    async with semaphore:
        try:
            result = await translator.translate(
                TranslationRequest(
                    text=text,
                    source_language=Language.ENGLISH,
                    target_language=target,
                    mode=PROMPT_MODE,
                )
            )
        except AppError as exc:
            print(f"  ! {key.value}: {exc}", file=sys.stderr)
            return key, None
        return key, result.text


async def generate_language(
    translator: ITranslator, target: Language, existing: dict[str, str]
) -> dict[str, str]:
    """Translate only what is missing, preserving anything already on disk.

    Committed prompts get hand-corrected - the first generated Hindi menu mixed
    formal and informal registers in one sentence. Regenerating wholesale would
    throw those fixes away every time a new prompt key is added.
    """
    todo = {key: text for key, text in ENGLISH_PROMPTS.items() if key.value not in existing}
    if not todo:
        return existing

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    results = await asyncio.gather(
        *(translate_prompt(translator, key, text, target, semaphore) for key, text in todo.items())
    )
    merged = dict(existing)
    merged.update({key.value: text for key, text in results if text is not None})
    return merged


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--languages",
        default=None,
        help="comma-separated language codes; default is all except English",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="re-translate prompts that already exist, discarding hand edits",
    )
    args = parser.parse_args()

    if args.languages:
        targets = [Language(code.strip()) for code in args.languages.split(",") if code.strip()]
    else:
        targets = [lang for lang in Language if lang is not Language.ENGLISH]

    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    providers = build_providers(get_settings())

    failures = 0
    try:
        for target in targets:
            path = PROMPTS_DIR / f"{target.value}.json"
            existing: dict[str, str] = (
                {}
                if args.overwrite or not path.exists()
                else json.loads(path.read_text(encoding="utf-8"))
            )

            todo_count = len([k for k in ENGLISH_PROMPTS if k.value not in existing])
            if not todo_count:
                print(f"{target.value}: up to date, nothing to translate")
                continue

            print(f"{target.value}: translating {todo_count} prompt(s)...")
            translations = await generate_language(providers.translator, target, existing)

            missing = len(ENGLISH_PROMPTS) - len(translations)
            if missing:
                failures += missing
                print(f"  ! {missing} prompt(s) failed; falls back to English at call time")

            path.write_text(
                json.dumps(translations, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"  wrote {path.relative_to(Path.cwd())}")
    finally:
        await providers.aclose()

    print("\nRead the generated files before trusting them on a real call.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
