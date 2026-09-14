"""Call and leg persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CallStatus, Language, LegDirection, LegState
from app.core.exceptions import LegNotFoundError
from app.models.base import utc_now
from app.models.call import Call, CallLeg


class PostgresCallRepository:
    """Implements ICallRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, room_code: str | None) -> Call:
        call = Call(room_code=room_code, status=CallStatus.PENDING)
        self._session.add(call)
        await self._session.flush()
        return call

    async def get(self, call_id: uuid.UUID) -> Call | None:
        return await self._session.get(Call, call_id)

    async def mark_bridged(self, call_id: uuid.UUID) -> None:
        call = await self._require(call_id)
        call.status = CallStatus.BRIDGED
        call.bridged_at = utc_now()
        await self._session.flush()

    async def mark_ended(self, call_id: uuid.UUID, *, reason: str) -> None:
        call = await self._require(call_id)
        # A call that never bridged ended in failure, not completion - that
        # distinction is what makes the pairing funnel measurable later.
        call.status = CallStatus.COMPLETED if call.bridged_at is not None else CallStatus.FAILED
        call.ended_at = utc_now()
        call.end_reason = reason
        await self._session.flush()

    async def _require(self, call_id: uuid.UUID) -> Call:
        call = await self._session.get(Call, call_id)
        if call is None:
            raise LegNotFoundError(f"no call {call_id}")
        return call


class PostgresCallLegRepository:
    """Implements ICallLegRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_provider_uuid(self, provider_call_uuid: str) -> CallLeg | None:
        result = await self._session.execute(
            select(CallLeg).where(CallLeg.provider_call_uuid == provider_call_uuid)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        provider_call_uuid: str,
        phone_e164: str,
        direction: LegDirection,
        user_id: uuid.UUID | None,
    ) -> CallLeg:
        leg = CallLeg(
            provider_call_uuid=provider_call_uuid,
            phone_e164=phone_e164,
            direction=direction,
            user_id=user_id,
            state=LegState.IDENTIFY,
            answered_at=utc_now(),
        )
        self._session.add(leg)
        await self._session.flush()
        return leg

    async def set_state(self, leg_id: uuid.UUID, state: LegState) -> CallLeg:
        leg = await self._require(leg_id)
        leg.state = state
        await self._session.flush()
        return leg

    async def attach_to_call(self, leg_id: uuid.UUID, call_id: uuid.UUID) -> CallLeg:
        leg = await self._require(leg_id)
        leg.call_id = call_id
        await self._session.flush()
        return leg

    async def snapshot_languages(
        self, leg_id: uuid.UUID, *, primary: Language, secondary: Language
    ) -> CallLeg:
        leg = await self._require(leg_id)
        leg.language_primary = primary
        leg.language_secondary = secondary
        await self._session.flush()
        return leg

    async def mark_ended(self, leg_id: uuid.UUID, *, hangup_cause: str | None) -> None:
        leg = await self._require(leg_id)
        leg.state = LegState.ENDED
        leg.ended_at = utc_now()
        leg.hangup_cause = hangup_cause
        await self._session.flush()

    async def _require(self, leg_id: uuid.UUID) -> CallLeg:
        leg = await self._session.get(CallLeg, leg_id)
        if leg is None:
            raise LegNotFoundError(f"no call leg {leg_id}")
        return leg
