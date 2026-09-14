"""Telephony abstractions (Adapter).

Vobiz is the vendor, but its XML dialect is Plivo-shaped and Pipecat ships
serializers for Plivo, Exotel and Twilio too. Keeping the seam means a carrier
swap is a new package under telephony/, not a rewrite of the IVR.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas.telephony import OutboundCallRequest, OutboundCallResult


@runtime_checkable
class ITelephonyProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def place_call(self, request: OutboundCallRequest) -> OutboundCallResult:
        """Dial a number and hand it to our answer URL once it connects."""
        ...

    async def hangup(self, provider_call_uuid: str) -> None: ...
