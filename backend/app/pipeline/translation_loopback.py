"""Phase 2: hear yourself translated.

One leg, the full AI path, output returned to the same caller:

    caller -> STT(source) -> translate -> TTS(target) -> caller

It is not the product - the product needs two legs - but it exercises every AI
component and every latency contributor except the second transport. If this
sounds right, Phase 4 is wiring, not discovery.
"""

from __future__ import annotations

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
from app.core.logging import get_logger
from app.pipeline.echo import TELEPHONY_SAMPLE_RATE
from app.pipeline.language_mapping import to_pipecat
from app.pipeline.processors.translation import TranslationProcessor
from app.providers.interfaces import ITranslator
from app.services.language_service import resolve_translation_mode
from app.telephony.vobiz.serializer import VobizFrameSerializer

logger = get_logger(__name__)


def _build_transport(
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
            # Local VAD gives turn events for observability and is the knob
            # PLAN 7.1 calls the biggest latency lever. Sarvam also endpoints
            # server-side; the two agreeing is the cheap version of PLAN 7.1's
            # layered detection.
            vad_analyzer=SileroVADAnalyzer(
                sample_rate=TELEPHONY_SAMPLE_RATE,
                params=VADParams(stop_secs=settings.pipeline.vad_stop_seconds),
            ),
        ),
    )


async def run_translation_loopback(
    websocket: WebSocket,
    *,
    stream_id: str,
    call_id: str | None,
    settings: Settings,
    translator: ITranslator,
) -> None:
    source = settings.pipeline.loopback_source_language
    target = settings.pipeline.loopback_target_language
    # The listener's own preferences pick the register. In the loopback the
    # listener is the speaker, so the secondary language is theirs too.
    mode = resolve_translation_mode(target, settings.call.default_secondary_language)

    transport = _build_transport(websocket, stream_id=stream_id, call_id=call_id, settings=settings)

    stt = SarvamRealtimeSTTService(
        api_key=settings.sarvam.api_key.get_secret_value(),
        sample_rate=TELEPHONY_SAMPLE_RATE,
        # No barge-in in v1: a caller talking over the output must not cancel it.
        should_interrupt=False,
        settings=SarvamRealtimeSTTService.Settings(
            model=settings.sarvam.stt_model,
            language=to_pipecat(source),
            mode=settings.sarvam.stt_mode.value,
            stream_type=settings.sarvam.stt_stream_type.value,
            # Server-side endpointing. This and the local VAD stop_secs are the
            # same knob seen from two sides; keeping them equal means one number
            # to tune when chasing the latency budget.
            silence_duration_ms=int(settings.pipeline.vad_stop_seconds * 1000),
        ),
    )

    tts = SarvamTTSService(
        api_key=settings.sarvam.api_key.get_secret_value(),
        sample_rate=TELEPHONY_SAMPLE_RATE,
        settings=SarvamTTSService.Settings(
            model=settings.sarvam.tts_model,
            voice=settings.sarvam.default_speaker.value,
            language=to_pipecat(target),
            # Normalising is exactly what we do not want (PLAN 7.4).
            enable_preprocessing=False,
        ),
    )

    translation = TranslationProcessor(
        translator=translator,
        source_language=source,
        target_language=target,
        mode=mode,
        max_chars=settings.sarvam.max_input_chars,
    )

    pipeline = Pipeline([transport.input(), stt, translation, tts, transport.output()])
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=TELEPHONY_SAMPLE_RATE,
            audio_out_sample_rate=TELEPHONY_SAMPLE_RATE,
        ),
        cancel_on_idle_timeout=False,
    )

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)

    logger.info(
        "translation_loopback_started",
        stream_id=stream_id,
        call_id=call_id,
        source=source.value,
        target=target.value,
        mode=mode.value,
    )
    try:
        await runner.run()
    finally:
        logger.info("translation_loopback_stopped", stream_id=stream_id, call_id=call_id)
