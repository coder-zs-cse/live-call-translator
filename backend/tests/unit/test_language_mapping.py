"""A missing mapping would only break one language, in production, for the
users least likely to be in anyone's test set. So assert the map is total."""

from __future__ import annotations

from app.core.enums import Language
from app.pipeline.language_mapping import to_pipecat


def test_every_language_maps() -> None:
    for language in Language:
        assert to_pipecat(language) is not None


def test_odia_bridges_the_sarvam_pipecat_spelling_difference() -> None:
    """Sarvam says od-IN, Pipecat says or-IN. This is the one that bites."""
    assert Language.ODIA.value == "od-IN"
    assert to_pipecat(Language.ODIA).value == "or-IN"
