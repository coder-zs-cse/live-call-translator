"""Vobiz REST client.

Only what the IVR needs: place a call, hang one up. Everything else Vobiz does
for us happens through Voice XML, not this API.
"""

from __future__ import annotations

import httpx

from app.core.config import VobizSettings
from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.schemas.telephony import OutboundCallRequest, OutboundCallResult

logger = get_logger(__name__)

PROVIDER_NAME = "vobiz"
_REQUEST_TIMEOUT_SECONDS = 10.0


class VobizClient:
    """Implements ITelephonyProvider."""

    def __init__(self, settings: VobizSettings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            auth=(settings.auth_id, settings.auth_token.get_secret_value()),
        )

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    @property
    def _account_path(self) -> str:
        return f"/api/v1/Account/{self._settings.auth_id}"

    async def place_call(self, request: OutboundCallRequest) -> OutboundCallResult:
        payload = {
            "from": request.from_number,
            "to": request.to_number,
            "answer_url": request.answer_url,
            "answer_method": "POST",
        }
        if request.hangup_url:
            payload["hangup_url"] = request.hangup_url

        try:
            response = await self._client.post(f"{self._account_path}/Call/", json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(PROVIDER_NAME, f"place_call failed: {exc}") from exc

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise ProviderError(
                PROVIDER_NAME,
                f"place_call returned {response.status_code}: {response.text[:300]}",
                status_code=response.status_code,
            )

        body = response.json()
        # Vobiz mirrors Plivo's response shape; request_uuid is what comes back
        # before the call is answered and a CallUUID exists.
        call_uuid = body.get("request_uuid") or body.get("call_uuid")
        if not call_uuid:
            raise ProviderError(PROVIDER_NAME, f"no call identifier in response: {body}")

        logger.info("outbound_call_placed", to=request.to_number, call_uuid=call_uuid)
        return OutboundCallResult(provider_call_uuid=call_uuid, provider=PROVIDER_NAME)

    async def hangup(self, provider_call_uuid: str) -> None:
        try:
            response = await self._client.delete(f"{self._account_path}/Call/{provider_call_uuid}/")
        except httpx.HTTPError as exc:
            # The call is ending anyway; a failed hangup is worth a log, not an
            # exception that propagates into a webhook response.
            logger.warning("vobiz_hangup_failed", call_uuid=provider_call_uuid, error=str(exc))
            return

        if response.status_code not in (204, 404):
            logger.warning(
                "vobiz_hangup_unexpected_status",
                call_uuid=provider_call_uuid,
                status=response.status_code,
            )

    async def aclose(self) -> None:
        await self._client.aclose()
