"""The answer webhook is what Vobiz hits first. If its XML is wrong the call
drops before anything else runs, so pin the contract."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from app.main import create_app

ANSWER_FORM = {
    "CallUUID": "abc-123",
    "From": "+919876543210",
    "To": "+911234567890",
    "Direction": "inbound",
}


def test_answer_returns_stream_xml() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/xml/answer", data=ANSWER_FORM)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")

    root = ET.fromstring(response.text)  # noqa: S314 - our own output
    stream = root.find("Stream")
    assert stream is not None
    assert stream.get("bidirectional") == "true"
    # Without this the call ends the instant the stream is established.
    assert stream.get("keepCallAlive") == "true"
    assert stream.get("contentType") == "audio/x-mulaw;rate=8000"
    assert stream.text is not None
    assert stream.text.startswith("wss://")


def test_answer_passes_call_uuid_to_the_media_socket() -> None:
    """The websocket has no other way to correlate itself with the call."""
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/xml/answer", data=ANSWER_FORM)

    stream = ET.fromstring(response.text).find("Stream")  # noqa: S314
    assert stream is not None
    assert stream.get("extraHeaders") == "callUuid=abc-123"


def test_stream_status_and_hangup_accept_vendor_posts() -> None:
    with TestClient(create_app()) as client:
        # "Event" is deliberate: it collides with structlog's own first argument
        # if the form is splatted into the log call instead of nested.
        status = client.post("/api/v1/xml/stream-status", data={"Event": "started"})
        assert status.status_code == 204
        assert client.post("/api/v1/xml/hangup", data=ANSWER_FORM).status_code == 204
