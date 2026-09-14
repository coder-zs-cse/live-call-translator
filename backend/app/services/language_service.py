"""Language preference rules.

Pure functions over enums: no I/O, no ORM. This is where the primary/secondary
requirement turns into a concrete Sarvam parameter, and it is the piece most
worth unit-testing, so it stays free of dependencies.
"""

from __future__ import annotations

from app.core.enums import (
    LANGUAGE_DISPLAY_NAMES,
    LANGUAGE_DTMF_MENU,
    Language,
    TranslationMode,
)


def resolve_translation_mode(
    target_primary: Language,
    target_secondary: Language,
) -> TranslationMode:
    """Pick the register for speech being delivered TO a listener.

    The listener's own preferences decide this, not the speaker's: a Hindi
    listener with English as secondary wants Hinglish, whatever language the
    other person is speaking.

    A secondary that differs from the primary is a request to keep loan words in
    that secondary language rather than forcing pure-target output - which is
    exactly what Sarvam calls code-mixed.
    """
    if target_secondary != target_primary:
        return TranslationMode.CODE_MIXED
    return TranslationMode.MODERN_COLLOQUIAL


def needs_language_setup(primary: Language | None, secondary: Language | None) -> bool:
    """First-time callers are asked to choose before anything else happens."""
    return primary is None or secondary is None


#: Spoken aliases callers actually use, beyond the canonical display names.
#: Speech recognition returns what was said, not a language code, so this is the
#: layer that has to be forgiving.
_SPOKEN_ALIASES: dict[str, Language] = {
    "hindi": Language.HINDI,
    "hindustani": Language.HINDI,
    "tamil": Language.TAMIL,
    "tamizh": Language.TAMIL,
    "thamizh": Language.TAMIL,
    "telugu": Language.TELUGU,
    "telegu": Language.TELUGU,
    "kannada": Language.KANNADA,
    "kannad": Language.KANNADA,
    "canarese": Language.KANNADA,
    "malayalam": Language.MALAYALAM,
    "marathi": Language.MARATHI,
    "marathee": Language.MARATHI,
    "bengali": Language.BENGALI,
    "bangla": Language.BENGALI,
    "gujarati": Language.GUJARATI,
    "gujrati": Language.GUJARATI,
    "punjabi": Language.PUNJABI,
    "panjabi": Language.PUNJABI,
    "odia": Language.ODIA,
    "oriya": Language.ODIA,
    "english": Language.ENGLISH,
}


def language_from_input(*, digits: str | None, speech: str | None) -> Language | None:
    """Resolve a caller's language from a <Gather> that accepted both inputs.

    Digits win when present: a keypress is unambiguous, speech is a guess.
    """
    if digits:
        return LANGUAGE_DTMF_MENU.get(digits.strip())

    if not speech:
        return None

    # Substring rather than equality: ASR returns whole utterances such as
    # "I speak Tamil" or "Tamil please", not a bare language name.
    spoken = speech.strip().lower()
    for alias, language in _SPOKEN_ALIASES.items():
        if alias in spoken:
            return language
    return None


def speech_hints() -> list[str]:
    """Bias the recogniser towards the closed set of language names."""
    return sorted(set(LANGUAGE_DISPLAY_NAMES.values()))
