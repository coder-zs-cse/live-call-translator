"""Puts two legs into one call.

Three routes in, one outcome: a `Call` with two legs attached. Keeping them in
one service is what stops "how does a leg get paired" being three different
answers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.enums import LegState, PairingMode
from app.core.exceptions import RoomNotFoundError
from app.core.logging import get_logger
from app.repositories.interfaces import ICallLegRepository, ICallRepository, IRoomRegistry

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PairResult:
    call_id: uuid.UUID
    peer_leg_id: uuid.UUID
    mode: PairingMode


class PairingService:
    def __init__(
        self,
        *,
        calls: ICallRepository,
        legs: ICallLegRepository,
        rooms: IRoomRegistry,
    ) -> None:
        self._calls = calls
        self._legs = legs
        self._rooms = rooms

    async def begin_wait(self, leg_id: uuid.UUID) -> None:
        """Start the hold timer for a leg waiting on a peer."""
        await self._rooms.begin_wait(leg_id)

    async def is_wait_active(self, leg_id: uuid.UUID) -> bool:
        return await self._rooms.is_wait_active(leg_id)

    async def create_room(self, leg_id: uuid.UUID) -> str:
        """Open a room and return the code to read out to the caller."""
        call = await self._calls.create(room_code=None)
        await self._legs.attach_to_call(leg_id, call.id)

        code = await self._rooms.allocate(leg_id=leg_id, call_id=call.id)
        logger.info("room_created", code=code, call_id=str(call.id), leg_id=str(leg_id))
        return code

    async def join_room(self, *, leg_id: uuid.UUID, code: str) -> PairResult:
        """Attach this leg to a waiting room.

        Raises RoomNotFoundError for an unknown, expired or already-claimed
        code - all three are the same thing to the caller, and distinguishing
        them out loud would tell a guesser which codes exist.
        """
        claimed = await self._rooms.claim(code)
        if claimed is None:
            raise RoomNotFoundError(f"room {code} is not available")

        creator_leg_id, call_id = claimed
        await self._legs.attach_to_call(leg_id, call_id)
        await self._calls.mark_bridged(call_id)
        # The creator is sitting in a wait poll. Without this their leg never
        # leaves WAIT_PEER and they are held on a silent line forever.
        await self._legs.set_state(creator_leg_id, LegState.BRIDGED)

        logger.info("room_joined", code=code, call_id=str(call_id), joiner_leg_id=str(leg_id))
        return PairResult(call_id=call_id, peer_leg_id=creator_leg_id, mode=PairingMode.ROOM_CODE)

    async def start_dial_out(self, leg_id: uuid.UUID) -> uuid.UUID:
        """Open a call for an outbound leg to join. Returns the call id.

        No room code: the callee is dialled directly, so there is nothing for
        anyone to enter and nothing to guess.
        """
        call = await self._calls.create(room_code=None)
        await self._legs.attach_to_call(leg_id, call.id)
        logger.info("dial_out_started", call_id=str(call.id), leg_id=str(leg_id))
        return call.id

    async def attach_dialed_leg(self, *, leg_id: uuid.UUID, call_id: uuid.UUID) -> PairResult:
        await self._legs.attach_to_call(leg_id, call_id)
        await self._calls.mark_bridged(call_id)
        logger.info("dialed_leg_attached", call_id=str(call_id), leg_id=str(leg_id))
        return PairResult(call_id=call_id, peer_leg_id=leg_id, mode=PairingMode.DIAL_OUT)
