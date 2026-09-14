"""Translates finalised transcripts and hands them to TTS.

Sits between STT and TTS in the pipeline. Everything it does not understand is
passed through untouched, which is what lets it be dropped into any pipeline
without knowing what else is in it.
"""

from __future__ import annotations

import time

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from app.core.enums import Language, TranslationMode
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.providers.interfaces import ITranslator
from app.schemas.translation import TranslationRequest

logger = get_logger(__name__)


class TranslationProcessor(FrameProcessor):
    """Turns a transcript in one language into speech text in another.

    Depends on ITranslator rather than a vendor, so the same processor serves
    whichever provider the Phase 2 eval picks.
    """

    def __init__(
        self,
        *,
        translator: ITranslator,
        source_language: Language,
        target_language: Language,
        mode: TranslationMode,
        max_chars: int,
    ) -> None:
        super().__init__()
        self._translator = translator
        self._source_language = source_language
        self._target_language = target_language
        self._mode = mode
        self._max_chars = max_chars
        #: Ordering guarantee for Phase 4 lives here; for now it is just an
        #: observability counter so logs can be correlated with audio.
        self._sequence = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        # Interim transcripts are for latency tricks later (see PLAN 7.1); acting
        # on them now would speak every half-finished sentence.
        if isinstance(frame, InterimTranscriptionFrame):
            return

        if not isinstance(frame, TranscriptionFrame):
            await self.push_frame(frame, direction)
            return

        text = frame.text.strip()
        if not text:
            return

        self._sequence += 1
        sequence = self._sequence

        for chunk in self._split(text):
            spoken = await self._translate(chunk, sequence)
            if spoken:
                await self.push_frame(TTSSpeakFrame(spoken), direction)

    async def _translate(self, text: str, sequence: int) -> str | None:
        started = time.perf_counter()
        try:
            result = await self._translator.translate(
                TranslationRequest(
                    text=text,
                    source_language=self._source_language,
                    target_language=self._target_language,
                    mode=self._mode,
                )
            )
        except AppError as exc:
            # One bad sentence must not take the call down. The speaker loses a
            # line and learns nothing was heard, which beats a dropped call.
            logger.warning(
                "translation_failed",
                sequence=sequence,
                source=self._source_language.value,
                target=self._target_language.value,
                error=str(exc),
            )
            return None

        logger.info(
            "utterance_translated",
            sequence=sequence,
            source=self._source_language.value,
            target=self._target_language.value,
            mode=self._mode.value,
            source_text=text,
            translated_text=result.text,
            provider_latency_ms=round(result.latency_ms, 1),
            total_latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return result.text

    def _split(self, text: str) -> list[str]:
        """Keep each request under the translator's input limit.

        Splits on sentence enders first so a break lands where a speaker paused,
        and only falls back to a hard cut if a single sentence is oversized.
        """
        if len(text) <= self._max_chars:
            return [text]

        chunks: list[str] = []
        current = ""
        for piece in _split_after(text, tuple(".?!\u0964")):
            if len(current) + len(piece) <= self._max_chars:
                current += piece
                continue
            if current:
                chunks.append(current.strip())
            while len(piece) > self._max_chars:
                chunks.append(piece[: self._max_chars].strip())
                piece = piece[self._max_chars :]
            current = piece
        if current.strip():
            chunks.append(current.strip())
        return [c for c in chunks if c]


def _split_after(text: str, enders: tuple[str, ...]) -> list[str]:
    """Split text into pieces, keeping the sentence-ending character attached."""
    pieces: list[str] = []
    current = ""
    for char in text:
        current += char
        if char in enders:
            pieces.append(current)
            current = ""
    if current:
        pieces.append(current)
    return pieces
