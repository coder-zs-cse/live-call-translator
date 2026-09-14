"""The primary/secondary requirement in one function, so pin its behaviour."""

from __future__ import annotations

from app.core.enums import Language, TranslationMode
from app.services.language_service import needs_language_setup, resolve_translation_mode


def test_distinct_secondary_requests_code_mixed_output() -> None:
    """Hindi primary + English secondary is the Hinglish case from the brief."""
    mode = resolve_translation_mode(Language.HINDI, Language.ENGLISH)
    assert mode is TranslationMode.CODE_MIXED


def test_matching_secondary_requests_plain_output() -> None:
    """The default is English/English, which must not become code-mixed."""
    mode = resolve_translation_mode(Language.ENGLISH, Language.ENGLISH)
    assert mode is TranslationMode.MODERN_COLLOQUIAL


def test_setup_is_required_until_both_languages_are_known() -> None:
    assert needs_language_setup(None, None) is True
    assert needs_language_setup(Language.HINDI, None) is True
    assert needs_language_setup(Language.HINDI, Language.ENGLISH) is False
