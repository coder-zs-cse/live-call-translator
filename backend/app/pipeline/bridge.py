"""Phase 4: two legs, cross-wired.

This is the product. Each direction is its own pipeline, and the two of them
never mix:

    A.in -> STT(A.primary) -> MT(A.primary -> B.primary) -> TTS(B) -> B.out
    B.in -> STT(B.primary) -> MT(B.primary -> A.primary) -> TTS(A) -> A.out

Note what is *absent*: nothing routes A's raw audio to B. Because each leg is a
separate call to us rather than a carrier bridge (docs/PLAN.md §2), "translated
voice only" is a property of the wiring, not a filter we have to maintain.

The awkward part is arrival: the two legs are two independent websocket
handlers, in two coroutines, connecting up to seconds apart. `BridgeRegistry` is
the rendezvous - whoever arrives second builds and runs both pipelines while the
first simply waits for them to finish.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.serializers.plivo import PlivoFrameSerializer
from pipecat.services.sarvam.stt import SarvamRealtimeSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner
from starlette.websockets import WebSocket

from app.core.config import Settings
from app.core.enums import Language
from app.core.logging import get_logger
from app.pipeline.echo import TELEPHONY_SAMPLE_RATE
from app.pipeline.language_mapping import to_pipecat
from app.pipeline.processors.translation import TranslationProcessor
from app.providers.interfaces import ITranslator
from app.services.language_service import resolve_translation_mode
from app.telephony.vobiz.serializer import VobizFrameSerializer

logger = get_logger(__name__)

#: How long the first leg waits for its peer's media stream. Pairing has already
#: happened by this point, so the peer is only as far away as one wait poll -
#: but a caller who hangs up between pairing and streaming must not strand a
#: coroutine forever.
PEER_ARRIVAL_TIMEOUT_SECONDS = 45.0


@dataclass(slots=True)
class BridgeLeg:
    """One side of a conversation, as the media plane sees it."""

    leg_id: uuid.UUID
    transport: FastAPIWebsocketTransport
    primary_language: Language
    secondary_language: Language


@dataclass(slots=True)
class BridgeSession:
    call_id: uuid.UUID
    legs: list[BridgeLeg] = field(default_factory=list)
    #: Set when the second leg's media stream connects.
    peer_arrived: asyncio.Event = field(default_factory=asyncio.Event)
    #: Set when the pipelines stop, so the first-arriving leg's handler can
    #: return and let its websocket close.
    finished: asyncio.Event = field(default_factory=asyncio.Event)


class BridgeRegistry:
    """In-process rendezvous for the two legs of a call.

    In-process is correct for v1 because both legs are served by one process
    (PLAN §10). When the media plane is split out, this is the seam that grows a
    sticky-routing lookup - not the pipelines.
    """

    def __init__(self) -> None:
        self._sessions: dict[uuid.UUID, BridgeSession] = {}
        self._lock = asyncio.Lock()

    async def join(self, call_id: uuid.UUID, leg: BridgeLeg) -> tuple[BridgeSession, bool]:
        """Add a leg. Returns the session and whether this leg completed it.

        The lock matters: both legs can arrive in the same event-loop tick, and
        without it both could believe they were first and neither would run the
        pipelines.
        """
        async with self._lock:
            session = self._sessions.setdefault(call_id, BridgeSession(call_id=call_id))
            session.legs.append(leg)
            is_complete = len(session.legs) == 2  # noqa: PLR2004 - a call has two legs
            if is_complete:
                session.peer_arrived.set()
            return session, is_complete

    async def discard(self, call_id: uuid.UUID) -> None:
        async with self._lock:
            self._sessions.pop(call_id, None)

    async def abandon(self, call_id: uuid.UUID, leg_id: uuid.UUID) -> None:
        """Remove one leg that left before the bridge was built."""
        async with self._lock:
            session = self._sessions.get(call_id)
            if session is None:
                return
            session.legs = [leg for leg in session.legs if leg.leg_id != leg_id]
            if not session.legs:
                self._sessions.pop(call_id, None)


def build_transport(
    websocket: WebSocket,
    *,
    stream_id: str,
    call_id: str | None,
    settings: Settings,
) -> FastAPIWebsocketTransport:
    serializer = VobizFrameSerializer(
        stream_id=stream_id,
        call_id=call_id,
        auth_id=settings.vobiz.auth_id,
        auth_token=settings.vobiz.auth_token.get_secret_value(),
        base_url=settings.vobiz.base_url,
        params=PlivoFrameSerializer.InputParams(
            plivo_sample_rate=TELEPHONY_SAMPLE_RATE,
            sample_rate=TELEPHONY_SAMPLE_RATE,
            auto_hang_up=bool(call_id),
        ),
    )
    return FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            serializer=serializer,
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=TELEPHONY_SAMPLE_RATE,
            audio_out_sample_rate=TELEPHONY_SAMPLE_RATE,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(
                sample_rate=TELEPHONY_SAMPLE_RATE,
                params=VADParams(stop_secs=settings.pipeline.vad_stop_seconds),
            ),
        ),
    )


def _build_direction(
    *,
    speaker: BridgeLeg,
    listener: BridgeLeg,
    settings: Settings,
    translator: ITranslator,
) -> Pipeline:
    """One-way: what the speaker says, in the listener's language.

    The listener's preferences choose the register - a Hindi listener with
    English as secondary wants Hinglish regardless of who is talking.
    """
    stt = SarvamRealtimeSTTService(
        api_key=settings.sarvam.api_key.get_secret_value(),
        sample_rate=TELEPHONY_SAMPLE_RATE,
        should_interrupt=False,
        settings=SarvamRealtimeSTTService.Settings(
            model=settings.sarvam.stt_model,
            language=to_pipecat(speaker.primary_language),
            mode=settings.sarvam.stt_mode.value,
            stream_type=settings.sarvam.stt_stream_type.value,
            silence_duration_ms=int(settings.pipeline.vad_stop_seconds * 1000),
        ),
    )

    translation = TranslationProcessor(
        translator=translator,
        source_language=speaker.primary_language,
        target_language=listener.primary_language,
        mode=resolve_translation_mode(listener.primary_language, listener.secondary_language),
        max_chars=settings.sarvam.max_input_chars,
    )

    tts = SarvamTTSService(
        api_key=settings.sarvam.api_key.get_secret_value(),
        sample_rate=TELEPHONY_SAMPLE_RATE,
        settings=SarvamTTSService.Settings(
            model=settings.sarvam.tts_model,
            voice=settings.sarvam.default_speaker.value,
            language=to_pipecat(listener.primary_language),
            enable_preprocessing=False,
        ),
    )

    # The speaker's input feeds the listener's output. That single line is the
    # bridge; everything else here is configuration.
    return Pipeline(
        [
            speaker.transport.input(),
            stt,
            translation,
            tts,
            listener.transport.output(),
        ]
    )


async def run_bridge(
    session: BridgeSession,
    *,
    settings: Settings,
    translator: ITranslator,
) -> None:
    """Run both directions until either caller hangs up."""
    first, second = session.legs

    worker_params = PipelineParams(
        audio_in_sample_rate=TELEPHONY_SAMPLE_RATE,
        audio_out_sample_rate=TELEPHONY_SAMPLE_RATE,
    )
    workers = [
        PipelineWorker(
            _build_direction(
                speaker=speaker, listener=listener, settings=settings, translator=translator
            ),
            params=worker_params,
            # Translation emits none of the frames Pipecat watches for idleness,
            # so the default idle cancel would end a quiet but live call.
            cancel_on_idle_timeout=False,
        )
        for speaker, listener in ((first, second), (second, first))
    ]

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(*workers)

    logger.info(
        "bridge_started",
        call_id=str(session.call_id),
        leg_a=str(first.leg_id),
        leg_b=str(second.leg_id),
        a_language=first.primary_language.value,
        b_language=second.primary_language.value,
    )
    try:
        await runner.run()
    finally:
        logger.info("bridge_stopped", call_id=str(session.call_id))


async def wait_for_bridge_to_finish(session: BridgeSession) -> bool:
    """Held by the first leg to arrive. False if its peer never showed up.

    Two waits, deliberately. Only *arrival* is bounded: once the bridge is
    running, this leg must stay open for as long as the conversation lasts, and
    a single timeout covering both would hang up on a call that was working.
    """
    try:
        await asyncio.wait_for(session.peer_arrived.wait(), PEER_ARRIVAL_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.warning("bridge_peer_never_arrived", call_id=str(session.call_id))
        return False

    await session.finished.wait()
    return True
