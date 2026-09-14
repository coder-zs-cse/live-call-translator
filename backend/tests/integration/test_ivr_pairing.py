"""Phase 3 acceptance: two callers pair, and languages persist between calls.

Runs against the real Postgres and Redis from infra/docker-compose.yml, because
the things most likely to break here are the atomic Redis operations and the
transaction boundaries - neither of which a fake would exercise.

Phone numbers are randomised per test so runs do not collide on the unique
index.
"""

from __future__ import annotations

import re
import secrets
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

DTMF_HINDI = "1"
DTMF_KEEP_ENGLISH = "1"
MENU_CREATE_ROOM = "1"
MENU_JOIN_ROOM = "3"


def phone() -> str:
    return f"+9190{secrets.randbelow(10**8):08d}"


def call_uuid(label: str) -> str:
    """Unique per run.

    A fixed CallUUID survives in Postgres between runs, and `on_answer` then
    reuses that stale leg - which still points at the previous run's user. The
    languages get written to the wrong row and the test fails on its second
    run. Real Vobiz UUIDs are unique per call; these must be too.
    """
    return f"{label}-{secrets.token_hex(6)}"


def form(call_uuid: str, from_number: str, **extra: str) -> dict[str, str]:
    return {
        "CallUUID": call_uuid,
        "From": from_number,
        "To": "+911234567890",
        "Direction": "inbound",
        **extra,
    }


def speak_lines(xml: str) -> list[str]:
    return [el.text or "" for el in ET.fromstring(xml).iter("Speak")]  # noqa: S314


def extract_room_code(xml: str) -> str:
    """The code is spoken digit by digit, e.g. '1 2 8 2'."""
    for line in speak_lines(xml):
        if re.fullmatch(r"(?:\d ){3}\d", line.strip()):
            return line.replace(" ", "")
    raise AssertionError(f"no spoken room code in: {speak_lines(xml)}")


def complete_language_setup(client: TestClient, call_uuid: str, number: str) -> None:
    client.post("/api/v1/xml/answer", data=form(call_uuid, number))
    client.post(
        "/api/v1/xml/language/primary",
        data=form(call_uuid, number, InputType="dtmf", Digits=DTMF_HINDI),
    )
    client.post(
        "/api/v1/xml/language/secondary",
        data=form(call_uuid, number, InputType="dtmf", Digits=DTMF_KEEP_ENGLISH),
    )


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app()) as test_client:
        yield test_client


def test_two_callers_pair_by_room_code(client: TestClient) -> None:
    creator, joiner = phone(), phone()
    uuid_call_a, uuid_call_b = call_uuid("call-a"), call_uuid("call-b")

    complete_language_setup(client, uuid_call_a, creator)
    created = client.post(
        "/api/v1/xml/menu", data=form(uuid_call_a, creator, Digits=MENU_CREATE_ROOM)
    )
    code = extract_room_code(created.text)
    assert len(code) == 4

    # The creator is now held in a polling Gather, not bridged.
    assert "<Stream" not in created.text
    waiting = client.post("/api/v1/xml/wait", data=form(uuid_call_a, creator))
    assert "<Stream" not in waiting.text

    complete_language_setup(client, uuid_call_b, joiner)
    client.post("/api/v1/xml/menu", data=form(uuid_call_b, joiner, Digits=MENU_JOIN_ROOM))
    joined = client.post("/api/v1/xml/room-code", data=form(uuid_call_b, joiner, Digits=code))

    # The joiner bridges immediately...
    assert "<Stream" in joined.text
    # ...and the creator's very next poll picks it up.
    bridged = client.post("/api/v1/xml/wait", data=form(uuid_call_a, creator))
    assert "<Stream" in bridged.text


def test_a_room_code_can_only_be_claimed_once(client: TestClient) -> None:
    """Otherwise a third caller could hijack a conversation in progress."""
    creator, first, second = phone(), phone(), phone()
    uuid_once_a, uuid_once_b, uuid_once_c = (
        call_uuid("once-a"),
        call_uuid("once-b"),
        call_uuid("once-c"),
    )

    complete_language_setup(client, uuid_once_a, creator)
    created = client.post(
        "/api/v1/xml/menu", data=form(uuid_once_a, creator, Digits=MENU_CREATE_ROOM)
    )
    code = extract_room_code(created.text)

    complete_language_setup(client, uuid_once_b, first)
    assert (
        "<Stream"
        in client.post("/api/v1/xml/room-code", data=form(uuid_once_b, first, Digits=code)).text
    )

    complete_language_setup(client, uuid_once_c, second)
    third = client.post("/api/v1/xml/room-code", data=form(uuid_once_c, second, Digits=code))
    assert "<Stream" not in third.text
    assert any("not found" in line.lower() for line in speak_lines(third.text))


def test_unknown_room_code_reprompts_rather_than_dropping_the_call(
    client: TestClient,
) -> None:
    number = phone()
    uuid_bad_code = call_uuid("bad-code")
    complete_language_setup(client, uuid_bad_code, number)
    client.post("/api/v1/xml/menu", data=form(uuid_bad_code, number, Digits=MENU_JOIN_ROOM))

    response = client.post("/api/v1/xml/room-code", data=form(uuid_bad_code, number, Digits="9999"))

    assert "<Gather" in response.text
    assert "<Hangup" not in response.text


def test_languages_persist_across_calls(client: TestClient) -> None:
    """The whole point of storing them: a returning caller is never re-asked."""
    number = phone()
    uuid_persist_1, uuid_persist_2 = call_uuid("persist-1"), call_uuid("persist-2")
    complete_language_setup(client, uuid_persist_1, number)

    # Second call, new CallUUID, same number.
    second = client.post("/api/v1/xml/answer", data=form(uuid_persist_2, number))

    lines = speak_lines(second.text)
    assert not any("Which language do you speak" in line for line in lines)
    # Straight to the menu, spoken in Hindi and English.
    assert len(lines) == 2


def test_a_returning_caller_hears_the_menu_in_both_languages(client: TestClient) -> None:
    number = phone()
    uuid_bilingual_1, uuid_bilingual_2 = (
        call_uuid("bilingual-1"),
        call_uuid("bilingual-2"),
    )
    complete_language_setup(client, uuid_bilingual_1, number)
    response = client.post("/api/v1/xml/answer", data=form(uuid_bilingual_2, number))

    lines = speak_lines(response.text)
    assert "Press 1 to create a room." in lines[1]
    # The Hindi line must not be the English one repeated.
    assert lines[0] != lines[1]
