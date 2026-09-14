"""The Vobiz serializer is an inheritance bet: that Vobiz speaks Plivo's wire
format. These tests pin the parts we actually rely on."""

from __future__ import annotations

import json

from pipecat.serializers.plivo import PlivoFrameSerializer

from app.telephony.vobiz.serializer import VobizFrameSerializer, parse_stream_start


def make_serializer() -> VobizFrameSerializer:
    return VobizFrameSerializer(
        stream_id="stream-1",
        call_id="call-1",
        auth_id="auth",
        auth_token="token",  # noqa: S106
    )


def test_inherits_plivo_wire_format() -> None:
    assert isinstance(make_serializer(), PlivoFrameSerializer)


def test_auto_hang_up_requires_credentials() -> None:
    """Constructing without a call id must fail loudly, not hang up silently."""
    try:
        VobizFrameSerializer(stream_id="stream-1")
    except ValueError as exc:
        assert "call_id" in str(exc)
    else:
        raise AssertionError("expected a ValueError for missing hangup credentials")


def test_hang_up_targets_vobiz_not_plivo() -> None:
    """PlivoFrameSerializer hardcodes api.plivo.com; that is the one thing we override."""
    serializer = VobizFrameSerializer(
        stream_id="s",
        call_id="c",
        auth_id="a",
        auth_token="t",  # noqa: S106
        base_url="https://api.vobiz.ai/",
    )
    assert serializer._base_url == "https://api.vobiz.ai"


def test_parse_stream_start_reads_nested_camel_case() -> None:
    message = json.loads('{"event":"start","start":{"streamId":"s1","callId":"c1"}}')
    assert parse_stream_start(message) == ("s1", "c1")


def test_parse_stream_start_accepts_flat_and_snake_case() -> None:
    """Field spelling is undocumented, so the parser tolerates variants."""
    assert parse_stream_start({"event": "start", "stream_id": "s2"}) == ("s2", None)
    assert parse_stream_start(
        {"event": "start", "start": {"StreamId": "s3", "CallUUID": "c3"}}
    ) == ("s3", "c3")


def test_parse_stream_start_ignores_other_events() -> None:
    assert parse_stream_start({"event": "media", "media": {"payload": "x"}}) is None
    assert parse_stream_start({"event": "start", "start": {}}) is None
