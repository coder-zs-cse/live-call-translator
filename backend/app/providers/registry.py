"""Factory Method for provider construction.

The point is that exactly one place branches on "which vendor". Swapping the
translator for an eval becomes a config change, not an edit at every call site.

Today there is one vendor, so this is a single-armed factory. It earns its place
because sharing one pooled HTTP client across the Sarvam services is real work
that has to live somewhere, and because Phase 2 commits to comparing providers.
If that comparison never happens, delete this and construct directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.providers.interfaces import ITextToSpeech, ITranslator
from app.providers.sarvam.client import SarvamHttpClient
from app.providers.sarvam.translator import SarvamTranslator
from app.providers.sarvam.tts import SarvamTextToSpeech


@dataclass(slots=True)
class ProviderBundle:
    """Everything the call path needs, sharing one connection pool."""

    translator: ITranslator
    text_to_speech: ITextToSpeech
    http: SarvamHttpClient

    async def aclose(self) -> None:
        await self.http.aclose()


def build_providers(settings: Settings) -> ProviderBundle:
    http = SarvamHttpClient(settings.sarvam)
    return ProviderBundle(
        translator=SarvamTranslator(settings.sarvam, http),
        text_to_speech=SarvamTextToSpeech(settings.sarvam, http),
        http=http,
    )
