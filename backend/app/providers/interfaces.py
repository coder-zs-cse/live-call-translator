"""Provider abstractions (Strategy).

What this buys: the pipeline depends on `ITranslator`, not on Sarvam, so a
provider can be swapped when an eval shows a better one, and tests can run
against fakes with no network. What it costs: one indirection per stage, and a
DTO round-trip on every call.

Protocols rather than ABCs — an implementation does not need to import this
module to satisfy it, which keeps the dependency arrow pointing one way.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas.translation import (
    SynthesisRequest,
    SynthesisResult,
    TranslationRequest,
    TranslationResult,
)


@runtime_checkable
class ITranslator(Protocol):
    """Text in one language to text in another, preserving the speaker's register."""

    @property
    def name(self) -> str: ...

    def supports(self, source: object, target: object) -> bool:
        """Whether this provider can serve the pair at all, checked before dialling."""
        ...

    async def translate(self, request: TranslationRequest) -> TranslationResult: ...


@runtime_checkable
class ITextToSpeech(Protocol):
    """Text to telephony-ready audio."""

    @property
    def name(self) -> str: ...

    def default_speaker(self, language: object) -> str: ...

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult: ...
