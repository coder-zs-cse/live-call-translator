"""Room codes and the pairing rendezvous.

Redis rather than Postgres because a room lives for minutes and is pure
coordination: nothing here is worth keeping once the call is bridged. The `Call`
row in Postgres is the durable record.

Two properties this has to guarantee, and both are why the operations are
Redis-atomic rather than read-then-write:

1. **No two live rooms share a code.** `SET NX` decides the winner when two
   callers press 1 at the same moment.
2. **A code pairs exactly one joiner.** `GETDEL` consumes the room, so a third
   caller entering the same code finds nothing rather than hijacking the call.
"""

from __future__ import annotations

import json
import secrets
import uuid

from redis.asyncio import Redis

from app.core.config import CallSettings, RedisSettings
from app.core.exceptions import RoomCodeExhaustedError
from app.core.logging import get_logger

logger = get_logger(__name__)

_KEY_PREFIX = "room:"
_WAIT_KEY_PREFIX = "room-wait:"


class RedisRoomRegistry:
    """Implements IRoomRegistry."""

    def __init__(
        self,
        redis: Redis,
        *,
        redis_settings: RedisSettings,
        call_settings: CallSettings,
    ) -> None:
        self._redis = redis
        self._ttl = redis_settings.room_ttl_seconds
        self._call = call_settings

    async def allocate(self, *, leg_id: uuid.UUID, call_id: uuid.UUID) -> str:
        payload = json.dumps({"leg_id": str(leg_id), "call_id": str(call_id)})

        for _ in range(self._call.room_code_allocation_attempts):
            code = self._random_code()
            # NX is the whole concurrency story: the loser of a race retries
            # with a different code instead of overwriting a live room.
            if await self._redis.set(_key(code), payload, nx=True, ex=self._ttl):
                logger.info("room_allocated", code=code, leg_id=str(leg_id))
                return code

        raise RoomCodeExhaustedError(
            f"no free room code after {self._call.room_code_allocation_attempts} attempts"
        )

    async def claim(self, code: str) -> tuple[uuid.UUID, uuid.UUID] | None:
        # GETDEL makes claiming one-shot and atomic, so two people entering the
        # same code at once cannot both be told they paired.
        raw = await self._redis.getdel(_key(code))
        if raw is None:
            logger.info("room_claim_missed", code=code)
            return None

        data = json.loads(raw)
        logger.info("room_claimed", code=code, leg_id=data["leg_id"])
        return uuid.UUID(data["leg_id"]), uuid.UUID(data["call_id"])

    async def release(self, code: str) -> None:
        await self._redis.delete(_key(code))

    async def begin_wait(self, leg_id: uuid.UUID) -> None:
        """Let Redis do the timing.

        A key with a TTL beats storing a timestamp and comparing clocks: there
        is no arithmetic to get wrong, and it expires on its own even if the
        caller hangs up and the poll never comes back.
        """
        await self._redis.set(_wait_key(leg_id), "1", ex=self._call.wait_peer_timeout_seconds)

    async def is_wait_active(self, leg_id: uuid.UUID) -> bool:
        return bool(await self._redis.exists(_wait_key(leg_id)))

    def _random_code(self) -> str:
        """Cryptographically random, not sequential.

        A 4-digit space is small enough to enumerate; predictable codes would
        make that trivial rather than merely possible. See PLAN section 4.4.
        """
        span = self._call.room_code_max - self._call.room_code_min + 1
        return str(self._call.room_code_min + secrets.randbelow(span))


def _key(code: str) -> str:
    return f"{_KEY_PREFIX}{code}"


def _wait_key(leg_id: uuid.UUID) -> str:
    return f"{_WAIT_KEY_PREFIX}{leg_id}"
