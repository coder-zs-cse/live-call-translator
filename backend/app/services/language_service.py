"""Language preference rules.

Pure functions over enums: no I/O, no ORM. This is where the primary/secondary
requirement turns into a concrete Sarvam parameter, and it is the piece most
worth unit-testing, so it stays free of dependencies.
"""

from __future__ import annotations

from app.core.enums import Language, TranslationMode


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
