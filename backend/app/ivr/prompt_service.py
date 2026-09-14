"""Renders prompts in a caller's languages.

The requirement is that menus are spoken in the caller's primary *and*
secondary language. That is two <Speak> elements per prompt, not one, and the
second is skipped when both languages are the same - which is the default, so
most callers hear one line rather than a stutter.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.core.enums import Language
from app.core.logging import get_logger
from app.ivr.catalog import ENGLISH_PROMPTS, PromptKey

logger = get_logger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


@lru_cache(maxsize=len(Language))
def _load(language: Language) -> dict[str, str]:
    """Translations for one language, or empty if none are committed yet."""
    path = PROMPTS_DIR / f"{language.value}.json"
    if not path.exists():
        return {}
    loaded: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


class PromptService:
    """Looks up prompt text. No I/O at call time - translations are on disk."""

    def text(self, key: PromptKey, language: Language) -> str:
        if language is Language.ENGLISH:
            return ENGLISH_PROMPTS[key]

        translated = _load(language).get(key.value)
        if translated:
            return translated

        # Falling back to English is the right failure: the caller hears
        # something they may not understand, rather than silence.
        logger.warning("prompt_missing", key=key.value, language=language.value)
        return ENGLISH_PROMPTS[key]

    def bilingual(self, key: PromptKey, *, primary: Language, secondary: Language) -> list[str]:
        """The prompt in both of a caller's languages, primary first.

        Deduplicated, because primary == secondary is the default and nobody
        wants to hear the menu twice.
        """
        lines = [self.text(key, primary)]
        if secondary is not primary:
            lines.append(self.text(key, secondary))
        return lines
