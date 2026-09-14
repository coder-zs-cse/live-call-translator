"""Builds Vobiz Voice XML responses.

Every attribute name and default in this file comes from the Vobiz XML docs. It
is the single place those spellings appear, so a vendor change or a doc
correction is a one-file edit.

Built with ElementTree rather than f-strings because caller-supplied text
(spoken prompts, phone numbers) ends up inside these documents and must be
escaped properly.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement, tostring

from app.core.enums import AudioCodec

_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'

#: Vobiz contentType strings. L16 at 8 kHz is the documented default; mulaw is
#: what Sarvam TTS can emit directly, which keeps a resample out of the path.
_CODEC_CONTENT_TYPE: dict[AudioCodec, str] = {
    AudioCodec.MULAW_8000: "audio/x-mulaw;rate=8000",
    AudioCodec.LINEAR16_8000: "audio/x-l16;rate=8000",
    AudioCodec.LINEAR16_16000: "audio/x-l16;rate=16000",
}

#: <Gather inputType>. Both means DTMF and speech are accepted at once, which is
#: how 22 languages become selectable on a 10-key pad.
INPUT_DTMF = "dtmf"
INPUT_SPEECH = "speech"
INPUT_BOTH = "dtmf speech"

#: Vobiz caps extraHeaders at 512 bytes.
_MAX_EXTRA_HEADERS_BYTES = 512


class VobizXmlBuilder:
    """Accumulates elements, then renders once.

    Deliberately not a fluent one-liner API: IVR handlers read better when the
    prompt, the gather and the fallback are separate statements.
    """

    def __init__(self) -> None:
        self._root = Element("Response")

    def speak(self, text: str, *, language: str | None = None) -> VobizXmlBuilder:
        element = SubElement(self._root, "Speak")
        if language:
            element.set("language", language)
        element.text = text
        return self

    def gather(
        self,
        *,
        action: str,
        prompts: list[str],
        num_digits: int | None = None,
        input_type: str = INPUT_DTMF,
        execution_timeout: int = 10,
        finish_on_key: str = "#",
        language: str | None = None,
        hints: list[str] | None = None,
    ) -> VobizXmlBuilder:
        """Collect input. Prompts nest inside so a keypress can interrupt them."""
        element = SubElement(self._root, "Gather")
        element.set("action", action)
        element.set("method", "POST")
        element.set("inputType", input_type)
        element.set("executionTimeout", str(execution_timeout))
        element.set("finishOnKey", finish_on_key)
        if num_digits is not None:
            element.set("numDigits", str(num_digits))
        if language:
            element.set("language", language)
        if hints:
            # Biases speech recognition. For language selection the hint list is
            # the language names themselves, which makes it near-deterministic.
            element.set("hints", ",".join(hints))

        for prompt in prompts:
            SubElement(element, "Speak").text = prompt
        return self

    def stream(
        self,
        *,
        websocket_url: str,
        codec: AudioCodec = AudioCodec.MULAW_8000,
        extra_headers: dict[str, str] | None = None,
        status_callback_url: str | None = None,
        stream_timeout_seconds: int = 3600,
        max_retries: int = 0,
    ) -> VobizXmlBuilder:
        """Hand the leg to the media pipeline for the rest of the call.

        keepCallAlive is always true: without it Vobiz moves on to the next XML
        element and the call ends the moment the stream is set up.
        """
        element = SubElement(self._root, "Stream")
        element.set("bidirectional", "true")
        # inbound = the caller's own voice. The far end does not exist on this
        # leg by design (docs/PLAN.md section 2), so there is nothing else to capture.
        element.set("audioTrack", "inbound")
        element.set("contentType", _CODEC_CONTENT_TYPE[codec])
        element.set("streamTimeout", str(stream_timeout_seconds))
        element.set("keepCallAlive", "true")
        element.set("maxRetries", str(max_retries))
        if status_callback_url:
            element.set("statusCallbackUrl", status_callback_url)
            element.set("statusCallbackMethod", "POST")
        if extra_headers:
            encoded = ",".join(f"{k}={v}" for k, v in sorted(extra_headers.items()))
            if len(encoded.encode("utf-8")) > _MAX_EXTRA_HEADERS_BYTES:
                raise ValueError(
                    f"extraHeaders is {len(encoded.encode('utf-8'))} bytes, "
                    f"limit is {_MAX_EXTRA_HEADERS_BYTES}"
                )
            element.set("extraHeaders", encoded)
        element.text = websocket_url
        return self

    def redirect(self, url: str) -> VobizXmlBuilder:
        element = SubElement(self._root, "Redirect")
        element.set("method", "POST")
        element.text = url
        return self

    def hangup(self, *, reason: str | None = None) -> VobizXmlBuilder:
        element = SubElement(self._root, "Hangup")
        if reason:
            element.set("reason", reason)
        return self

    def render(self) -> str:
        body = tostring(self._root, encoding="unicode")
        return f"{_XML_DECLARATION}\n{body}"
