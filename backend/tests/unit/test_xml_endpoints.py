"""The XML the webhooks return.

These assert the *shape* Vobiz needs. Getting it wrong drops the call before
anything else runs, and the symptom on a real phone is just silence - so the
contract is pinned here rather than discovered by dialling.

The pairing behaviour behind these endpoints is covered in
tests/integration/test_ivr_pairing.py, which uses a real Postgres and Redis.
"""

from __future__ import annotations

import secrets
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from app.main import create_app


def answer_form() -> dict[str, str]:
    return {
        "CallUUID": f"xml-{secrets.token_hex(6)}",
        "From": f"+9190{secrets.randbelow(10**8):08d}",
        "To": "+911234567890",
        "Direction": "inbound",
    }


def parse(xml: str) -> ET.Element:
    return ET.fromstring(xml)  # noqa: S314 - our own output


def test_answer_asks_a_new_caller_for_their_language() -> None:
    """A number we have never seen cannot be given a menu it may not understand."""
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/xml/answer", data=answer_form())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")

    gather = parse(response.text).find("Gather")
    assert gather is not None
    # Speech and DTMF together: 11 languages do not fit a 10-key pad.
    assert gather.get("inputType") == "dtmf speech"
    assert gather.get("hints") is not None
    assert any("Which language do you speak" in (s.text or "") for s in gather.findall("Speak"))


def test_prompts_sit_inside_the_gather_so_a_keypress_can_interrupt_them() -> None:
    """Prompts placed after a Gather cannot be barged; the caller waits them out."""
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/xml/answer", data=answer_form())

    root = parse(response.text)
    assert root.find("Speak") is None
    gather = root.find("Gather")
    assert gather is not None
    assert gather.findall("Speak")


def test_a_gather_is_followed_by_a_redirect_fallback() -> None:
    """Without it, a Gather that times out with no input ends in dead air."""
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/xml/answer", data=answer_form())

    assert [child.tag for child in parse(response.text)] == ["Gather", "Redirect"]


def test_stream_status_and_hangup_accept_vendor_posts() -> None:
    with TestClient(create_app()) as client:
        # "Event" is deliberate: it collides with structlog's own first argument
        # if the form is splatted into the log call instead of nested.
        status = client.post("/api/v1/xml/stream-status", data={"Event": "started"})
        assert status.status_code == 204
        assert client.post("/api/v1/xml/hangup", data=answer_form()).status_code == 204


def test_primary_language_dtmf_does_not_500_on_blank_speech_score() -> None:
    """Vobiz posts SpeechConfidenceScore= on a DTMF gather; that must not 500."""
    payload = answer_form()
    with TestClient(create_app()) as client:
        answered = client.post("/api/v1/xml/answer", data=payload)
        assert answered.status_code == 200
        response = client.post(
            "/api/v1/xml/language/primary",
            data={
                **payload,
                "InputType": "dtmf",
                "Digits": "1",
                "Speech": "",
                "SpeechConfidenceScore": "",
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
