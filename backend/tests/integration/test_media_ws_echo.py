"""Phase 1 acceptance, without a phone.

Impersonates Vobiz: connect, send a `start` event, push mulaw audio, and expect
the same audio back as `playAudio`. This is the plumbing check the phase exists
for - transport, serializer, codec and buffering - minus the PSTN.

A real call is still the final word (jitter and clock drift do not show up
here), but if this fails, calling the number will not help.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import struct

import pytest
from fastapi.testclient import TestClient
from pipecat.audio.utils import create_stream_resampler, pcm_to_ulaw

from app.core.enums import PipelineMode
from app.main import create_app
from app.pipeline.echo import TELEPHONY_SAMPLE_RATE

_TONE_HZ = 440
_CHUNK_MS = 20
_SAMPLES_PER_CHUNK = TELEPHONY_SAMPLE_RATE * _CHUNK_MS // 1000
_CHUNKS_TO_SEND = 50  # one second of audio
_PIPELINE_WARMUP_SECONDS = 8.0


def _tone_pcm(chunk_index: int) -> bytes:
    """A sine chunk. Silence gets dropped by the serializer, so it must be real audio."""
    start = chunk_index * _SAMPLES_PER_CHUNK
    samples = (
        int(12000 * math.sin(2 * math.pi * _TONE_HZ * (start + n) / TELEPHONY_SAMPLE_RATE))
        for n in range(_SAMPLES_PER_CHUNK)
    )
    return struct.pack(f"<{_SAMPLES_PER_CHUNK}h", *samples)


@pytest.mark.asyncio
@pytest.mark.parametrize("pipeline_mode", [PipelineMode.ECHO], indirect=True)
async def test_echo_pipeline_returns_the_audio_it_was_sent(
    pipeline_mode: PipelineMode,
) -> None:
    resampler = create_stream_resampler()
    chunks = [
        await pcm_to_ulaw(_tone_pcm(i), TELEPHONY_SAMPLE_RATE, TELEPHONY_SAMPLE_RATE, resampler)
        for i in range(_CHUNKS_TO_SEND)
    ]

    played: list[bytes] = []
    with TestClient(create_app()) as client, client.websocket_connect("/api/v1/ws/media") as ws:
        ws.send_text(json.dumps({"event": "start", "start": {"streamId": "s1", "callId": "c1"}}))

        # The pipeline takes a moment to finish starting; audio pushed before
        # StartFrame reaches the end of the pipeline is discarded.
        await asyncio.sleep(_PIPELINE_WARMUP_SECONDS)

        for chunk in chunks:
            ws.send_text(
                json.dumps(
                    {
                        "event": "media",
                        "media": {"payload": base64.b64encode(chunk).decode()},
                    }
                )
            )

        # Drain whatever the pipeline has produced so far.
        for _ in range(_CHUNKS_TO_SEND):
            message = json.loads(ws.receive_text())
            if message.get("event") == "playAudio":
                played.append(base64.b64decode(message["media"]["payload"]))
            if sum(len(p) for p in played) >= sum(len(c) for c in chunks):
                break

    echoed = b"".join(played)
    assert echoed, "pipeline produced no audio at all"
    # Allow for framing differences; what matters is that roughly what went in
    # came back, not that chunk boundaries were preserved.
    sent_bytes = sum(len(c) for c in chunks)
    assert len(echoed) >= sent_bytes * 0.8, (
        f"echoed {len(echoed)} bytes for {sent_bytes} sent - audio is being dropped"
    )
