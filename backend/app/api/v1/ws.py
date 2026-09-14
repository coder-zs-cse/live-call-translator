"""Media websocket: where Vobiz streams call audio.

The handler's only job is the handshake - accept, read the `start` event to
learn the stream and call ids, then hand the socket to a pipeline. Everything
after that belongs to Pipecat.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.core.logging import get_logger
from app.pipeline.echo import run_echo_pipeline
from app.telephony.vobiz.serializer import parse_stream_start

logger = get_logger(__name__)

router = APIRouter(prefix="/ws", tags=["media"])

#: Vobiz may send a connected/handshake frame before `start`. Read a few frames
#: looking for it rather than assuming it arrives first.
_MAX_HANDSHAKE_FRAMES = 5


async def _read_stream_start(websocket: WebSocket) -> tuple[str, str | None] | None:
    for _ in range(_MAX_HANDSHAKE_FRAMES):
        raw = await websocket.receive_text()
        try:
            message: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("media_ws_non_json_frame", raw=raw[:200])
            continue

        # Logged in full because the exact `start` field spelling is not in the
        # Vobiz docs. The first real call is what pins it down.
        # Note: structlog's own first argument is named `event`, so the vendor's
        # event name has to travel under a different key.
        logger.info("media_ws_frame", vobiz_event=message.get("event"), payload=message)

        parsed = parse_stream_start(message)
        if parsed:
            return parsed
    return None


@router.websocket("/media")
async def media(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()

    try:
        parsed = await _read_stream_start(websocket)
    except WebSocketDisconnect:
        logger.info("media_ws_disconnected_during_handshake")
        return

    if not parsed:
        logger.error("media_ws_no_start_event")
        await websocket.close(code=1002, reason="expected a start event")
        return

    stream_id, call_id = parsed
    logger.info("media_ws_connected", stream_id=stream_id, call_id=call_id)

    try:
        await run_echo_pipeline(
            websocket, stream_id=stream_id, call_id=call_id, settings=settings.vobiz
        )
    except WebSocketDisconnect:
        logger.info("media_ws_closed_by_peer", stream_id=stream_id)
