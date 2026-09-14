"""Prompt lookup, including the fallbacks that keep a call alive."""

from __future__ import annotations

from app.core.enums import Language
from app.ivr.catalog import ENGLISH_PROMPTS, PromptKey, speak_digits
from app.ivr.prompt_service import PromptService


def test_english_comes_from_the_catalog() -> None:
    service = PromptService()
    assert (
        service.text(PromptKey.MAIN_MENU, Language.ENGLISH)
        == (ENGLISH_PROMPTS[PromptKey.MAIN_MENU])
    )


def test_missing_translation_falls_back_to_english_rather_than_silence() -> None:
    service = PromptService()
    # Odia has the least chance of a committed translation; whatever the state
    # of the files, the caller must hear words.
    assert service.text(PromptKey.GOODBYE, Language.ODIA)


def test_bilingual_returns_both_languages_primary_first() -> None:
    service = PromptService()
    lines = service.bilingual(
        PromptKey.MAIN_MENU, primary=Language.HINDI, secondary=Language.ENGLISH
    )
    assert len(lines) == 2
    assert lines[1] == ENGLISH_PROMPTS[PromptKey.MAIN_MENU]


def test_bilingual_does_not_repeat_when_both_languages_match() -> None:
    """English/English is the default; hearing the menu twice would be a bug."""
    service = PromptService()
    lines = service.bilingual(
        PromptKey.MAIN_MENU, primary=Language.ENGLISH, secondary=Language.ENGLISH
    )
    assert len(lines) == 1


def test_room_codes_are_spoken_digit_by_digit() -> None:
    """Otherwise TTS says 'one thousand two hundred and eighty-two'."""
    assert speak_digits("1282") == "1 2 8 2"


def test_every_prompt_key_has_english_text() -> None:
    """A missing key would only surface as a KeyError mid-call."""
    for key in PromptKey:
        assert ENGLISH_PROMPTS[key].strip()
