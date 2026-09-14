"""Vobiz Voice XML webhooks.

Thin by design: parse the vendor's form post into a DTO, ask a service what
should happen, render XML. No business rules here.

Phase 1 has no service to ask yet - every call goes straight to the echo
pipeline. Phase 3 replaces the body of `answer` with an IVR state machine call.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.core.enums import AudioCodec
from app.core.logging import get_logger
from app.dependencies import SettingsDep
from app.schemas.telephony import InboundCallWebhook
from app.telephony.vobiz.xml_builder import VobizXmlBuilder

logger = get_logger(__name__)

router = APIRouter(prefix="/xml", tags=["telephony"])

XML_MEDIA_TYPE = "application/xml"


async def _parse_webhook(request: Request) -> InboundCallWebhook:
    """Vobiz posts form-encoded, with its own capitalised field names."""
    form = await request.form()
    return InboundCallWebhook.model_validate({k: str(v) for k, v in form.items()})


@router.post("/answer")
async def answer(request: Request, settings: SettingsDep) -> Response:
    """Called when a leg connects. Hands it straight to the media pipeline."""
    webhook = await _parse_webhook(request)
    logger.info(
        "inbound_call",
        call_uuid=webhook.call_uuid,
        from_number=webhook.from_number,
        to_number=webhook.to_number,
        direction=webhook.direction,
    )

    xml = (
        VobizXmlBuilder()
        .speak("Connecting you to the echo test. Say something.")
        .stream(
            websocket_url=settings.vobiz.stream_url,
            codec=AudioCodec.MULAW_8000,
            extra_headers={"callUuid": webhook.call_uuid},
            status_callback_url=f"{settings.vobiz.public_base_url}/api/v1/xml/stream-status",
        )
        .render()
    )
    return Response(content=xml, media_type=XML_MEDIA_TYPE)


@router.post("/stream-status")
async def stream_status(request: Request) -> Response:
    """Stream lifecycle events. Logged only, until Phase 5 gives them a home."""
    form = await request.form()
    # Nested rather than splatted: a vendor field named "event" would collide
    # with structlog's own first argument.
    logger.info("stream_status", payload={k: str(v) for k, v in form.items()})
    return Response(status_code=204)


@router.post("/hangup")
async def hangup(request: Request) -> Response:
    form = await request.form()
    logger.info("call_hangup", payload={k: str(v) for k, v in form.items()})
    return Response(status_code=204)
