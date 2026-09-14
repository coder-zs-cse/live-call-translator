"""Vobiz Voice XML webhooks.

Thin by design: parse the vendor's form post into a DTO, ask the IVR service
what should happen, render the answer as XML. Every decision lives in
`IvrService`; everything here is translation between Vobiz's vocabulary and
ours.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.core.config import Settings
from app.core.enums import AudioCodec
from app.core.logging import get_logger
from app.dependencies import IvrServiceDep, SettingsDep, TelephonyDep
from app.ivr.directives import IvrDirective
from app.schemas.telephony import GatherWebhook, InboundCallWebhook, OutboundCallRequest
from app.telephony.vobiz.xml_builder import INPUT_BOTH, INPUT_DTMF, VobizXmlBuilder

logger = get_logger(__name__)

router = APIRouter(prefix="/xml", tags=["telephony"])

XML_MEDIA_TYPE = "application/xml"


async def _form(request: Request) -> dict[str, str]:
    form = await request.form()
    return {key: str(value) for key, value in form.items()}


def _render(directive: IvrDirective, settings: Settings, call_uuid: str) -> Response:
    """Turn an IvrDirective into Vobiz XML.

    The ordering rule that matters: prompts go *inside* a <Gather> when one
    follows, so a caller who already knows the menu can press a key over it
    instead of waiting out the whole prompt.
    """
    builder = VobizXmlBuilder()

    if directive.gather is not None:
        spec = directive.gather
        builder.gather(
            action=f"{settings.vobiz.public_base_url}{spec.action_path}",
            prompts=directive.speak,
            num_digits=spec.num_digits,
            input_type=INPUT_BOTH if spec.accept_speech else INPUT_DTMF,
            execution_timeout=spec.execution_timeout,
            finish_on_key=spec.finish_on_key,
            hints=spec.hints or None,
        )
        # Reached only if the Gather times out with no input at all. Without a
        # fallback the call would simply go silent and drop.
        builder.redirect(f"{settings.vobiz.public_base_url}{spec.action_path}")
    else:
        for line in directive.speak:
            builder.speak(line)

    if directive.bridge:
        builder.stream(
            websocket_url=settings.vobiz.stream_url,
            codec=AudioCodec.MULAW_8000,
            extra_headers={"callUuid": call_uuid},
            status_callback_url=(f"{settings.vobiz.public_base_url}/api/v1/xml/stream-status"),
        )

    if directive.hangup:
        builder.hangup()

    return Response(content=builder.render(), media_type=XML_MEDIA_TYPE)


@router.post("/answer")
async def answer(request: Request, settings: SettingsDep, ivr: IvrServiceDep) -> Response:
    webhook = InboundCallWebhook.model_validate(await _form(request))
    logger.info(
        "inbound_call",
        call_uuid=webhook.call_uuid,
        from_number=webhook.from_number,
        direction=webhook.direction,
    )
    directive = await ivr.on_answer(webhook)
    return _render(directive, settings, webhook.call_uuid)


@router.post("/language/primary")
async def language_primary(request: Request, settings: SettingsDep, ivr: IvrServiceDep) -> Response:
    webhook = GatherWebhook.model_validate(await _form(request))
    directive = await ivr.on_primary_language(webhook)
    return _render(directive, settings, webhook.call_uuid)


@router.post("/language/secondary")
async def language_secondary(
    request: Request, settings: SettingsDep, ivr: IvrServiceDep
) -> Response:
    webhook = GatherWebhook.model_validate(await _form(request))
    directive = await ivr.on_secondary_language(webhook)
    return _render(directive, settings, webhook.call_uuid)


@router.post("/menu")
async def menu(request: Request, settings: SettingsDep, ivr: IvrServiceDep) -> Response:
    webhook = GatherWebhook.model_validate(await _form(request))
    directive = await ivr.on_menu_choice(webhook)
    return _render(directive, settings, webhook.call_uuid)


@router.post("/room-code")
async def room_code(request: Request, settings: SettingsDep, ivr: IvrServiceDep) -> Response:
    webhook = GatherWebhook.model_validate(await _form(request))
    directive = await ivr.on_room_code(webhook)
    return _render(directive, settings, webhook.call_uuid)


@router.post("/wait")
async def wait(request: Request, settings: SettingsDep, ivr: IvrServiceDep) -> Response:
    """Polled by a caller holding a room open, until someone joins."""
    webhook = GatherWebhook.model_validate(await _form(request))
    directive = await ivr.on_wait_poll(webhook)
    return _render(directive, settings, webhook.call_uuid)


@router.post("/phone-number")
async def phone_number(
    request: Request,
    settings: SettingsDep,
    ivr: IvrServiceDep,
    telephony: TelephonyDep,
) -> Response:
    """Dial the number the caller entered, then hold them until it answers."""
    webhook = GatherWebhook.model_validate(await _form(request))
    directive, number = await ivr.on_phone_number(webhook)

    if number:
        # Placing the call is I/O against the carrier, so it happens here rather
        # than inside the state machine.
        await telephony.place_call(
            OutboundCallRequest(
                to_number=number,
                from_number=settings.vobiz.phone_number,
                answer_url=settings.vobiz.answer_url,
                hangup_url=settings.vobiz.hangup_url,
            )
        )

    return _render(directive, settings, webhook.call_uuid)


@router.post("/stream-status")
async def stream_status(request: Request) -> Response:
    """Stream lifecycle events. Logged only, until Phase 5 gives them a home."""
    logger.info("stream_status", payload=await _form(request))
    return Response(status_code=204)


@router.post("/hangup")
async def hangup(request: Request) -> Response:
    logger.info("call_hangup", payload=await _form(request))
    return Response(status_code=204)
