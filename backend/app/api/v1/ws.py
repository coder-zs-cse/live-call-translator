"""Media websocket: where Vobiz streams call audio.

The handler does the handshake, works out which leg and which call this socket
belongs to, and hands it to a pipeline. Everything after that is Pipecat's.

Which pipeline depends on whether the leg has a peer. A leg that reached
`<Stream>` through the IVR is paired, so it bridges; `PIPELINE__MODE` still
selects the Phase 1/2 test pipelines for a leg that has no call attached, which
is what makes solo test calls possible without touching config.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import Settings, get_settings
from app.core.enums import PipelineMode
from app.core.logging import get_logger
from app.models.call import CallLeg
from app.pipeline.bridge import (
    BridgeLeg,
    build_transport,
    run_bridge,
    wait_for_bridge_to_finish,
)
from app.pipeline.echo import run_echo_pipeline
from app.pipeline.translation_loopback import run_translation_loopback
from app.providers.registry import ProviderBundle
from app.repositories.postgres.call_repository import PostgresCallLegRepository
from app.repositories.postgres.session import session_scope
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
        # Vobiz docs. Note: structlog's own first argument is named `event`, so
        # the vendor's event name travels under a different key.
        logger.info("media_ws_frame", vobiz_event=message.get("event"), payload=message)

        parsed = parse_stream_start(message)
        if parsed:
            return parsed
    return None


async def _load_leg(websocket: WebSocket, provider_call_uuid: str | None) -> CallLeg | None:
    """Find the leg this socket belongs to, by the carrier's call id."""
    if not provider_call_uuid:
        return None

    async for session in session_scope(websocket.app.state.session_factory):
        return await PostgresCallLegRepository(session).get_by_provider_uuid(provider_call_uuid)
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

    stream_id, provider_call_uuid = parsed
    leg = await _load_leg(websocket, provider_call_uuid)

    logger.info(
        "media_ws_connected",
        stream_id=stream_id,
        provider_call_uuid=provider_call_uuid,
        leg_id=str(leg.id) if leg else None,
        call_id=str(leg.call_id) if leg and leg.call_id else None,
    )

    providers: ProviderBundle = websocket.app.state.providers
    try:
        if leg is not None and leg.call_id is not None:
            await _run_bridge_leg(
                websocket,
                leg=leg,
                call_id=leg.call_id,
                stream_id=stream_id,
                provider_call_uuid=provider_call_uuid,
                settings=settings,
                providers=providers,
            )
            return

        # No call attached: a solo test call, not a paired conversation.
        logger.info("media_ws_unpaired_leg", mode=settings.pipeline.mode.value)
        await _run_test_pipeline(
            websocket,
            stream_id=stream_id,
            call_id=provider_call_uuid,
            settings=settings,
            providers=providers,
        )
    except WebSocketDisconnect:
        logger.info("media_ws_closed_by_peer", stream_id=stream_id)


async def _run_bridge_leg(
    websocket: WebSocket,
    *,
    leg: CallLeg,
    call_id: uuid.UUID,
    stream_id: str,
    provider_call_uuid: str | None,
    settings: Settings,
    providers: ProviderBundle,
) -> None:
    """Join this leg to its call, then bridge once both sides are streaming."""
    registry = websocket.app.state.bridges

    bridge_leg = BridgeLeg(
        leg_id=leg.id,
        transport=build_transport(
            websocket,
            stream_id=stream_id,
            call_id=provider_call_uuid,
            settings=settings,
        ),
        primary_language=leg.language_primary or settings.call.default_primary_language,
        secondary_language=(leg.language_secondary or settings.call.default_secondary_language),
    )

    session, is_complete = await registry.join(call_id, bridge_leg)

    if not is_complete:
        # First to arrive. Hold the socket open; the peer's handler runs both
        # pipelines, using the transport built above.
        arrived = await wait_for_bridge_to_finish(session)
        if not arrived:
            await registry.abandon(call_id, leg.id)
        return

    try:
        await run_bridge(session, settings=settings, translator=providers.translator)
    finally:
        # Release the waiting leg whatever happened, or its handler never
        # returns and the websocket leaks.
        session.finished.set()
        await registry.discard(call_id)


async def _run_test_pipeline(
    websocket: WebSocket,
    *,
    stream_id: str,
    call_id: str | None,
    settings: Settings,
    providers: ProviderBundle,
) -> None:
    """Phase 1/2 single-leg pipelines, for calls that were never paired."""
    if settings.pipeline.mode is PipelineMode.ECHO:
        await run_echo_pipeline(
            websocket, stream_id=stream_id, call_id=call_id, settings=settings.vobiz
        )
        return

    await run_translation_loopback(
        websocket,
        stream_id=stream_id,
        call_id=call_id,
        settings=settings,
        translator=providers.translator,
    )
