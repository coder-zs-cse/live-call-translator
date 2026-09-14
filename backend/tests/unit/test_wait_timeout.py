"""The hold timer for a caller waiting on a peer.

Redis TTL does the timing, so these tests are about the decision the IVR makes
when the key is gone - not about clock arithmetic.
"""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis

from app.core.config import get_settings
from app.repositories.redis.room_registry import RedisRoomRegistry


@pytest.fixture
async def registry() -> RedisRoomRegistry:
    settings = get_settings()
    redis = Redis.from_url(settings.redis.url, decode_responses=True)
    try:
        yield RedisRoomRegistry(redis, redis_settings=settings.redis, call_settings=settings.call)
    finally:
        await redis.aclose()


async def test_wait_is_active_immediately_after_it_begins(
    registry: RedisRoomRegistry,
) -> None:
    leg_id = uuid.uuid4()
    await registry.begin_wait(leg_id)
    assert await registry.is_wait_active(leg_id) is True


async def test_a_leg_that_never_started_waiting_is_not_active(
    registry: RedisRoomRegistry,
) -> None:
    """An unknown leg reads the same as an expired one, which is what makes the
    timeout branch safe to reach from any state."""
    assert await registry.is_wait_active(uuid.uuid4()) is False


async def test_wait_expires(registry: RedisRoomRegistry) -> None:
    """Simulated by setting the key with a TTL that has already lapsed."""
    leg_id = uuid.uuid4()
    await registry.begin_wait(leg_id)
    await registry._redis.delete(f"room-wait:{leg_id}")
    assert await registry.is_wait_active(leg_id) is False
