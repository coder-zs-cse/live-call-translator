"""Maps our Language enum onto Pipecat's.

Written out in full rather than derived by string munging, because the two do
not agree: Sarvam spells Odia `od-IN` and Pipecat spells it `or-IN`. A clever
one-liner would silently produce an invalid language for exactly one of the 11
languages, and only for the users least likely to be in the test set.
"""

from __future__ import annotations

from pipecat.transcriptions.language import Language as PipecatLanguage

from app.core.enums import Language

_TO_PIPECAT: dict[Language, PipecatLanguage] = {
    Language.ENGLISH: PipecatLanguage.EN_IN,
    Language.HINDI: PipecatLanguage.HI_IN,
    Language.BENGALI: PipecatLanguage.BN_IN,
    Language.TAMIL: PipecatLanguage.TA_IN,
    Language.TELUGU: PipecatLanguage.TE_IN,
    Language.GUJARATI: PipecatLanguage.GU_IN,
    Language.KANNADA: PipecatLanguage.KN_IN,
    Language.MALAYALAM: PipecatLanguage.ML_IN,
    Language.MARATHI: PipecatLanguage.MR_IN,
    Language.PUNJABI: PipecatLanguage.PA_IN,
    # Sarvam: od-IN. Pipecat: or-IN. Neither is wrong; they just differ.
    Language.ODIA: PipecatLanguage.OR_IN,
}


def to_pipecat(language: Language) -> PipecatLanguage:
    try:
        return _TO_PIPECAT[language]
    except KeyError as exc:  # pragma: no cover - guarded by test_every_language_maps
        raise ValueError(f"no Pipecat language mapping for {language}") from exc
