"""Sarvam Mayura translation.

POST https://api.sarvam.ai/translate
"""

from __future__ import annotations

import time

from app.core.config import SarvamSettings
from app.core.enums import Language
from app.core.exceptions import TranslationFailedError, UnsupportedLanguagePairError
from app.core.logging import get_logger
from app.providers.sarvam.client import PROVIDER_NAME, SarvamHttpClient
from app.schemas.translation import TranslationRequest, TranslationResult

logger = get_logger(__name__)

_TRANSLATE_PATH = "/translate"

#: Mayura documents bidirectional support *with English*. Whether an Indic->Indic
#: pair is served directly or pivoted through English is unconfirmed, and it
#: matters: a pivot roughly doubles this stage's share of the latency budget.
#: scripts/spike_translation.py measures it. See docs/PLAN.md section 7.4.
_SUPPORTED = set(Language)


class SarvamTranslator:
    """Implements ITranslator."""

    def __init__(self, settings: SarvamSettings, client: SarvamHttpClient) -> None:
        self._settings = settings
        self._client = client

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def supports(self, source: object, target: object) -> bool:
        return source in _SUPPORTED and target in _SUPPORTED and source != target

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        if not self.supports(request.source_language, request.target_language):
            raise UnsupportedLanguagePairError(
                f"{self.name} cannot translate "
                f"{request.source_language} -> {request.target_language}"
            )

        if len(request.text) > self._settings.max_input_chars:
            # Splitting is the utterance assembler's job; arriving here means a
            # boundary rule upstream failed, and silently truncating would put
            # words in the speaker's mouth.
            raise TranslationFailedError(
                self.name,
                f"input is {len(request.text)} chars, limit is {self._settings.max_input_chars}",
            )

        payload = {
            "input": request.text,
            "source_language_code": request.source_language.value,
            "target_language_code": request.target_language.value,
            "model": self._settings.translate_model,
            "mode": request.mode.value,
            "output_script": self._settings.output_script.value,
            # The requirement is a faithful translation, not a tidied one. Sarvam
            # preprocessing normalises the input, which is exactly the behaviour we
            # do not want when the speaker's grammar is meant to survive.
            "enable_preprocessing": False,
        }

        started = time.perf_counter()
        body = await self._client.post_json(_TRANSLATE_PATH, payload)
        latency_ms = (time.perf_counter() - started) * 1000

        translated = body.get("translated_text")
        if not translated:
            raise TranslationFailedError(self.name, f"no translated_text in response: {body}")

        logger.debug(
            "translated",
            source=request.source_language.value,
            target=request.target_language.value,
            mode=request.mode.value,
            latency_ms=round(latency_ms, 1),
        )

        return TranslationResult(
            text=translated,
            source_language=request.source_language,
            target_language=request.target_language,
            mode=request.mode,
            provider=self.name,
            model=self._settings.translate_model,
            latency_ms=latency_ms,
            request_id=body.get("request_id"),
        )
