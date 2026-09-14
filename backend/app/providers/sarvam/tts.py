"""Sarvam Bulbul text-to-speech.

POST https://api.sarvam.ai/text-to-speech, which returns base64 audio.

This is the batch endpoint. Phase 1 replaces it on the call path with the
streaming websocket, so the first audio byte leaves before the full sentence is
synthesised - but batch is the right shape for the spikes and for IVR prompts,
which are short and cacheable.
"""

from __future__ import annotations

import base64
import binascii
import time

from app.core.config import SarvamSettings
from app.core.enums import AudioCodec, Language
from app.core.exceptions import TextToSpeechFailedError
from app.providers.sarvam.client import PROVIDER_NAME, SarvamHttpClient
from app.schemas.translation import SynthesisRequest, SynthesisResult

_TTS_PATH = "/text-to-speech"

#: Sarvam codec names differ from our wire enum; this is the only place that
#: knows the mapping. MULAW_8000 is the happy path: Vobiz speaks it natively, so
#: no resampling sits in the latency budget.
_CODEC_TO_SARVAM: dict[AudioCodec, str] = {
    AudioCodec.MULAW_8000: "mulaw",
    AudioCodec.LINEAR16_8000: "linear16",
    AudioCodec.LINEAR16_16000: "linear16",
}

_CODEC_SAMPLE_RATE: dict[AudioCodec, int] = {
    AudioCodec.MULAW_8000: 8000,
    AudioCodec.LINEAR16_8000: 8000,
    AudioCodec.LINEAR16_16000: 16000,
}

#: Curated per language. Default voice quality varies a lot across Indic
#: languages, so this map is worth revisiting with real listening tests rather
#: than trusting one voice everywhere.
_DEFAULT_SPEAKERS: dict[Language, str] = dict.fromkeys(Language, "anushka")
_FALLBACK_SPEAKER = "anushka"


class SarvamTextToSpeech:
    """Implements ITextToSpeech."""

    def __init__(self, settings: SarvamSettings, client: SarvamHttpClient) -> None:
        self._settings = settings
        self._client = client

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def default_speaker(self, language: object) -> str:
        if isinstance(language, Language):
            return _DEFAULT_SPEAKERS.get(language, _FALLBACK_SPEAKER)
        return _FALLBACK_SPEAKER

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        payload = {
            "text": request.text,
            "target_language_code": request.language.value,
            "speaker": request.speaker,
            "model": self._settings.tts_model,
            "pace": request.pace,
            "output_audio_codec": _CODEC_TO_SARVAM[request.codec],
            "speech_sample_rate": _CODEC_SAMPLE_RATE[request.codec],
            "enable_preprocessing": False,
        }

        started = time.perf_counter()
        body = await self._client.post_json(_TTS_PATH, payload)
        latency_ms = (time.perf_counter() - started) * 1000

        audios = body.get("audios") or []
        if not audios:
            raise TextToSpeechFailedError(self.name, f"no audio in response: {body}")

        try:
            audio = base64.b64decode(audios[0])
        except (binascii.Error, ValueError) as exc:
            raise TextToSpeechFailedError(self.name, f"audio was not valid base64: {exc}") from exc

        return SynthesisResult(
            audio=audio,
            codec=request.codec,
            provider=self.name,
            model=self._settings.tts_model,
            latency_ms=latency_ms,
        )
