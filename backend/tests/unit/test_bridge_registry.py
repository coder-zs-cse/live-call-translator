"""The rendezvous between two media streams.

This is the piece with real concurrency in it: two websocket handlers, two
coroutines, arriving in either order and possibly in the same event-loop tick.
Getting it wrong means either nobody runs the pipelines or both do.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import cast

import pytest

from app.core.enums import Language
from app.pipeline.bridge import (
    PEER_ARRIVAL_TIMEOUT_SECONDS,
    BridgeLeg,
    BridgeRegistry,
    wait_for_bridge_to_finish,
)


def make_leg() -> BridgeLeg:
    return BridgeLeg(
        leg_id=uuid.uuid4(),
        # The registry never touches the transport; it only carries it.
        transport=cast("object", None),  # type: ignore[arg-type]
        primary_language=Language.HINDI,
        secondary_language=Language.ENGLISH,
    )


async def test_first_leg_does_not_complete_the_session() -> None:
    registry = BridgeRegistry()
    session, is_complete = await registry.join(uuid.uuid4(), make_leg())

    assert is_complete is False
    assert session.peer_arrived.is_set() is False


async def test_second_leg_completes_the_session_exactly_once() -> None:
    """Only one of the two handlers may run the pipelines."""
    registry = BridgeRegistry()
    call_id = uuid.uuid4()

    _, first_complete = await registry.join(call_id, make_leg())
    session, second_complete = await registry.join(call_id, make_leg())

    assert [first_complete, second_complete] == [False, True]
    assert len(session.legs) == 2
    assert session.peer_arrived.is_set() is True


async def test_simultaneous_arrival_still_elects_one_runner() -> None:
    """Both legs can arrive in the same tick; the lock is what decides."""
    registry = BridgeRegistry()
    call_id = uuid.uuid4()

    results = await asyncio.gather(
        registry.join(call_id, make_leg()),
        registry.join(call_id, make_leg()),
    )

    assert sum(1 for _, is_complete in results if is_complete) == 1


async def test_separate_calls_do_not_share_a_session() -> None:
    """Otherwise two unrelated conversations would be bridged into each other."""
    registry = BridgeRegistry()
    session_a, _ = await registry.join(uuid.uuid4(), make_leg())
    session_b, complete_b = await registry.join(uuid.uuid4(), make_leg())

    assert session_a is not session_b
    assert complete_b is False


async def test_abandoning_the_only_leg_drops_the_session() -> None:
    registry = BridgeRegistry()
    call_id = uuid.uuid4()
    leg = make_leg()
    await registry.join(call_id, leg)

    await registry.abandon(call_id, leg.leg_id)

    # A later arrival starts fresh rather than pairing with a hung-up caller.
    _, is_complete = await registry.join(call_id, make_leg())
    assert is_complete is False


async def test_waiting_leg_returns_false_when_no_peer_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = BridgeRegistry()
    session, _ = await registry.join(uuid.uuid4(), make_leg())

    monkeypatch.setattr("app.pipeline.bridge.PEER_ARRIVAL_TIMEOUT_SECONDS", 0.05)
    assert await wait_for_bridge_to_finish(session) is False


async def test_waiting_leg_stays_open_for_the_whole_call() -> None:
    """Arrival is bounded; the conversation is not.

    A single timeout covering both would hang up on a call that was working.
    """
    registry = BridgeRegistry()
    call_id = uuid.uuid4()
    session, _ = await registry.join(call_id, make_leg())
    await registry.join(call_id, make_leg())

    waiter = asyncio.create_task(wait_for_bridge_to_finish(session))
    await asyncio.sleep(0.05)

    # Peer has arrived, so it must not have returned - even though it would
    # have if the arrival timeout also governed call duration.
    assert not waiter.done()
    assert PEER_ARRIVAL_TIMEOUT_SECONDS > 0.05

    session.finished.set()
    assert await waiter is True
