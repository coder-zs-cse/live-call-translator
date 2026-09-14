"""DTOs that cross the provider boundary.

Deliberately framework-free: no HTTP objects, no ORM models. A service can build
one of these without knowing which vendor will serve it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AudioCodec, Language, TranslationMode


class TranslationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1)
    source_language: Language
    target_language: Language
    #: Drives register. CODE_MIXED is how a user's secondary language is honoured.
    mode: TranslationMode = TranslationMode.MODERN_COLLOQUIAL


class TranslationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    source_language: Language
    target_language: Language
    mode: TranslationMode
    provider: str
    model: str
    #: Wall-clock time spent inside the provider call. Feeds the latency budget.
    latency_ms: float
    request_id: str | None = None


class SynthesisRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1)
    language: Language
    speaker: str
    codec: AudioCodec = AudioCodec.MULAW_8000
    pace: float = 1.0


class SynthesisResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    audio: bytes
    codec: AudioCodec
    provider: str
    model: str
    latency_ms: float
