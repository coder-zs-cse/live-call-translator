"""Persistence abstractions.

Services depend on these, never on SQLAlchemy or redis-py. That is what lets the
IVR state machine - the part with all the branching - be unit-tested against
in-memory fakes rather than a live Postgres.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from app.core.enums import Language, LegDirection, LegState
from app.models.call import Call, CallLeg
from app.models.user import User


@runtime_checkable
class IUserRepository(Protocol):
    async def get_by_phone(self, phone_e164: str) -> User | None: ...

    async def create(self, phone_e164: str) -> User: ...

    async def set_languages(
        self, user_id: uuid.UUID, *, primary: Language, secondary: Language
    ) -> User: ...

    async def touch_last_call(self, user_id: uuid.UUID) -> None: ...


@runtime_checkable
class ICallLegRepository(Protocol):
    async def get_by_provider_uuid(self, provider_call_uuid: str) -> CallLeg | None: ...

    async def create(
        self,
        *,
        provider_call_uuid: str,
        phone_e164: str,
        direction: LegDirection,
        user_id: uuid.UUID | None,
    ) -> CallLeg: ...

    async def set_state(self, leg_id: uuid.UUID, state: LegState) -> CallLeg: ...

    async def attach_to_call(self, leg_id: uuid.UUID, call_id: uuid.UUID) -> CallLeg: ...

    async def snapshot_languages(
        self, leg_id: uuid.UUID, *, primary: Language, secondary: Language
    ) -> CallLeg:
        """Freeze the languages this call actually used.

        The user row can change later; what a past call did must not.
        """
        ...

    async def mark_ended(self, leg_id: uuid.UUID, *, hangup_cause: str | None) -> None: ...


@runtime_checkable
class ICallRepository(Protocol):
    async def create(self, *, room_code: str | None) -> Call: ...

    async def get(self, call_id: uuid.UUID) -> Call | None: ...

    async def mark_bridged(self, call_id: uuid.UUID) -> None: ...

    async def mark_ended(self, call_id: uuid.UUID, *, reason: str) -> None: ...


@runtime_checkable
class IRoomRegistry(Protocol):
    """Ephemeral pairing state. Redis, not Postgres - rooms live for minutes.

    Kept behind an interface from day one because it is the piece that would be
    painful to retrofit when the media plane is split out (PLAN section 10).
    """

    async def allocate(self, *, leg_id: uuid.UUID, call_id: uuid.UUID) -> str:
        """Reserve an unused room code. Raises RoomCodeExhaustedError if it cannot."""
        ...

    async def claim(self, code: str) -> tuple[uuid.UUID, uuid.UUID] | None:
        """Consume a waiting room, returning (leg_id, call_id) of its creator.

        One-shot: a code can never pair a third caller.
        """
        ...

    async def release(self, code: str) -> None: ...

    async def begin_wait(self, leg_id: uuid.UUID) -> None:
        """Start the clock on a caller holding an unclaimed room."""
        ...

    async def is_wait_active(self, leg_id: uuid.UUID) -> bool:
        """False once the caller has waited longer than the configured limit."""
        ...
