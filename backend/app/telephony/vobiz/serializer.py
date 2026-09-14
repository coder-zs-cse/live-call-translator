"""Pipecat frame serializer for Vobiz audio streams.

Pipecat 1.10 ships serializers for exotel, genesys, plivo, telnyx, twilio and
vonage - there is no Vobiz one. But Vobiz's streaming protocol is Plivo's, event
for event and field for field:

    inbound   {"event": "media", "media": {"payload": <base64>}}
              {"event": "dtmf",  "dtmf":  {"digit": "1"}}
    outbound  {"event": "playAudio", "media": {"contentType": "audio/x-mulaw",
                                               "sampleRate": 8000,
                                               "payload": <base64>},
               "streamId": ...}
              {"event": "clearAudio", "streamId": ...}

So we inherit rather than reimplement. The one genuine difference is the hangup
REST call, which PlivoFrameSerializer hardcodes to api.plivo.com.

If Vobiz ever diverges, this is the file that absorbs it.
"""

from __future__ import annotations

from typing import Any

import httpx
from pipecat.serializers.plivo import PlivoFrameSerializer

from app.core.logging import get_logger

logger = get_logger(__name__)

_HANGUP_TIMEOUT_SECONDS = 5.0


class VobizFrameSerializer(PlivoFrameSerializer):
    """Plivo's wire format against Vobiz's REST API."""

    def __init__(
        self,
        stream_id: str,
        *,
        call_id: str | None = None,
        auth_id: str | None = None,
        auth_token: str | None = None,
        base_url: str = "https://api.vobiz.ai",
        params: PlivoFrameSerializer.InputParams | None = None,
    ) -> None:
        super().__init__(
            stream_id=stream_id,
            call_id=call_id,
            auth_id=auth_id,
            auth_token=auth_token,
            params=params,
        )
        self._base_url = base_url.rstrip("/")

    async def _hang_up_call(self) -> None:
        """Terminate the call through Vobiz rather than Plivo.

        Vobiz namespaces its REST API under /api/v1 where Plivo uses /v1.
        """
        if not (self._call_id and self._auth_id and self._auth_token):
            return

        endpoint = f"{self._base_url}/api/v1/Account/{self._auth_id}/Call/{self._call_id}/"
        try:
            async with httpx.AsyncClient(timeout=_HANGUP_TIMEOUT_SECONDS) as client:
                response = await client.delete(endpoint, auth=(self._auth_id, self._auth_token))
        except httpx.HTTPError as exc:
            # A failed hangup must never take the pipeline down with it - the
            # call is already ending, and Vobiz will reap it on its own.
            logger.warning("vobiz_hangup_failed", call_id=self._call_id, error=str(exc))
            return

        if response.status_code in (204, 404):
            logger.debug("vobiz_hangup_ok", call_id=self._call_id, status=response.status_code)
        else:
            logger.warning(
                "vobiz_hangup_unexpected_status",
                call_id=self._call_id,
                status=response.status_code,
                body=response.text[:200],
            )


def parse_stream_start(message: dict[str, Any]) -> tuple[str, str | None] | None:
    """Pull (stream_id, call_id) out of the Vobiz `start` event.

    The exact field spelling is not in the public docs, so this accepts the
    plausible variants and the caller logs the raw payload. The first real test
    call settles it; once it does, collapse this to the one true spelling.
    """
    if message.get("event") != "start":
        return None

    start = message.get("start", message)
    stream_id = _first_present(start, ("streamId", "stream_id", "StreamId"))
    if not stream_id:
        return None

    call_id = _first_present(start, ("callId", "call_id", "callUUID", "CallUUID"))
    return stream_id, call_id


def _first_present(source: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    return None
