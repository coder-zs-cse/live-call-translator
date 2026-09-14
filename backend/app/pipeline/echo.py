"""Phase 1: the echo bot.

Proves the media path end to end - PSTN in, websocket, Pipecat, websocket, PSTN
out - before any AI is involved. If your own voice comes back clean, with no
jitter and no doubling, the transport, codec, resampling and buffering are all
correct, and every later problem is an AI problem rather than a plumbing one.

The pipeline is deliberately two elements. Resist adding anything here: the
value of this phase is that a failure has exactly one possible cause.
"""

from __future__ import annotations

from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.serializers.plivo import PlivoFrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner
from starlette.websockets import WebSocket

from app.core.config import VobizSettings
from app.core.logging import get_logger
from app.telephony.vobiz.serializer import VobizFrameSerializer

logger = get_logger(__name__)

#: Vobiz streams 8 kHz mulaw. Keeping the pipeline at 8 kHz too means no
#: resampling on either edge - one less thing to blame for jitter.
TELEPHONY_SAMPLE_RATE = 8000


class AudioLoopback(FrameProcessor):
    """Turns captured audio back into playable audio.

    A transport's input emits InputAudioRawFrame and its output only writes
    OutputAudioRawFrame, so wiring input() straight to output() produces
    silence - the frames travel the pipeline and are ignored at the end. This
    one-line conversion is the whole echo bot.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, InputAudioRawFrame):
            await self.push_frame(
                OutputAudioRawFrame(
                    audio=frame.audio,
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels,
                ),
                direction,
            )
        else:
            await self.push_frame(frame, direction)


def build_echo_transport(
    websocket: WebSocket,
    *,
    stream_id: str,
    call_id: str | None,
    settings: VobizSettings,
) -> FastAPIWebsocketTransport:
    serializer = VobizFrameSerializer(
        stream_id=stream_id,
        call_id=call_id,
        auth_id=settings.auth_id,
        auth_token=settings.auth_token.get_secret_value(),
        base_url=settings.base_url,
        params=PlivoFrameSerializer.InputParams(
            plivo_sample_rate=TELEPHONY_SAMPLE_RATE,
            sample_rate=TELEPHONY_SAMPLE_RATE,
            # Needs call_id to be real. On the very first test call we may not
            # know the field spelling yet, so only arm it when we have one.
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
            # No VAD: an echo bot has no turns to detect, and leaving it out
            # keeps this phase's failure modes down to transport and codec.
            add_wav_header=False,
        ),
    )


async def run_echo_pipeline(
    websocket: WebSocket,
    *,
    stream_id: str,
    call_id: str | None,
    settings: VobizSettings,
) -> None:
    """Run until the caller hangs up or Vobiz closes the stream."""
    transport = build_echo_transport(
        websocket, stream_id=stream_id, call_id=call_id, settings=settings
    )

    pipeline = Pipeline([transport.input(), AudioLoopback(), transport.output()])
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=TELEPHONY_SAMPLE_RATE, audio_out_sample_rate=TELEPHONY_SAMPLE_RATE
        ),
        # An echo bot emits none of the frames Pipecat watches for idleness, so
        # the default 5-minute idle cancel would end a long quiet call.
        cancel_on_idle_timeout=False,
    )

    # handle_sigint stays off: this runs inside the web server's event loop, and
    # signal handling belongs to uvicorn.
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)

    logger.info("echo_pipeline_started", stream_id=stream_id, call_id=call_id)
    try:
        await runner.run()
    finally:
        logger.info("echo_pipeline_stopped", stream_id=stream_id, call_id=call_id)
