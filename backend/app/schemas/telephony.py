"""DTOs for the telephony boundary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import LegDirection


class OutboundCallRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    to_number: str
    from_number: str
    answer_url: str
    hangup_url: str | None = None


class OutboundCallResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_call_uuid: str
    provider: str


class InboundCallWebhook(BaseModel):
    """Parameters Vobiz POSTs to the answer URL.

    Field names are the vendor's (CallUUID, From, To); this DTO is the one place
    that spelling is allowed to appear, so the rest of the app speaks snake_case.
    """

    model_config = ConfigDict(populate_by_name=True)

    call_uuid: str = Field(alias="CallUUID")
    from_number: str = Field(alias="From")
    to_number: str = Field(alias="To")
    direction: str = Field(alias="Direction")


class GatherWebhook(InboundCallWebhook):
    """Adds what <Gather> collected. Either digits or speech, per InputType."""

    input_type: str | None = Field(default=None, alias="InputType")
    digits: str | None = Field(default=None, alias="Digits")
    speech: str | None = Field(default=None, alias="Speech")
    speech_confidence: float | None = Field(default=None, alias="SpeechConfidenceScore")


class LegIdentity(BaseModel):
    """Correlates a Vobiz call with our own leg record across webhooks."""

    model_config = ConfigDict(frozen=True)

    leg_id: str
    provider_call_uuid: str
    direction: LegDirection
