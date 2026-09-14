"""The XML builder is pure and vendor-shaped, so it is worth pinning exactly."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from app.core.enums import AudioCodec
from app.telephony.vobiz.xml_builder import INPUT_BOTH, VobizXmlBuilder


def parse(xml: str) -> ET.Element:
    return ET.fromstring(xml)  # noqa: S314 - our own output


def test_speak_escapes_caller_supplied_text() -> None:
    xml = VobizXmlBuilder().speak("Fish & chips <loudly>").render()
    assert "&amp;" in xml
    assert "<loudly>" not in xml
    assert parse(xml).find("Speak").text == "Fish & chips <loudly>"


def test_gather_sets_documented_attributes() -> None:
    xml = (
        VobizXmlBuilder()
        .gather(
            action="https://example.com/menu",
            prompts=["Press 1", "Ek dabaaiye"],
            num_digits=1,
            input_type=INPUT_BOTH,
            hints=["Hindi", "Tamil"],
        )
        .render()
    )
    gather = parse(xml).find("Gather")
    assert gather.get("action") == "https://example.com/menu"
    assert gather.get("inputType") == "dtmf speech"
    assert gather.get("numDigits") == "1"
    assert gather.get("finishOnKey") == "#"
    assert gather.get("hints") == "Hindi,Tamil"
    # Prompts nest inside so a keypress can cut them off.
    assert [s.text for s in gather.findall("Speak")] == ["Press 1", "Ek dabaaiye"]


def test_stream_keeps_the_call_alive() -> None:
    """Without keepCallAlive the call ends as soon as the stream is set up."""
    xml = VobizXmlBuilder().stream(websocket_url="wss://example.com/ws").render()
    stream = parse(xml).find("Stream")
    assert stream.get("keepCallAlive") == "true"
    assert stream.get("bidirectional") == "true"
    assert stream.get("audioTrack") == "inbound"
    assert stream.text == "wss://example.com/ws"


def test_stream_codec_maps_to_vendor_content_type() -> None:
    xml = VobizXmlBuilder().stream(websocket_url="wss://e/ws", codec=AudioCodec.MULAW_8000).render()
    assert parse(xml).find("Stream").get("contentType") == "audio/x-mulaw;rate=8000"


def test_stream_extra_headers_are_sorted_and_encoded() -> None:
    xml = (
        VobizXmlBuilder()
        .stream(websocket_url="wss://e/ws", extra_headers={"leg": "abc", "call": "xyz"})
        .render()
    )
    assert parse(xml).find("Stream").get("extraHeaders") == "call=xyz,leg=abc"


def test_stream_rejects_oversized_extra_headers() -> None:
    """Vobiz caps this at 512 bytes; failing here beats a truncated leg id."""
    with pytest.raises(ValueError, match="limit is 512"):
        VobizXmlBuilder().stream(
            websocket_url="wss://e/ws",
            extra_headers={"blob": "x" * 600},
        )


def test_elements_render_in_call_order() -> None:
    xml = (
        VobizXmlBuilder()
        .speak("Your room code is 1 2 8 2")
        .gather(action="https://e/wait", prompts=["Waiting"], num_digits=1)
        .hangup()
        .render()
    )
    assert [child.tag for child in parse(xml)] == ["Speak", "Gather", "Hangup"]
