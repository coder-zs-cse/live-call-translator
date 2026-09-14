"""Vendor form posts at the telephony DTO boundary."""

from __future__ import annotations

from app.schemas.telephony import GatherWebhook


def test_dtmf_gather_treats_blank_speech_fields_as_absent() -> None:
    """Vobiz includes Speech and SpeechConfidenceScore even when InputType is dtmf.

    An empty SpeechConfidenceScore used to 500 the language webhook because
    pydantic cannot parse "" as a float.
    """
    webhook = GatherWebhook.model_validate(
        {
            "CallUUID": "cd835ab1-98dc-4048-8c2c-a7285f9dc301",
            "From": "919325617129",
            "To": "+917971442643",
            "Direction": "inbound",
            "InputType": "dtmf",
            "Digits": "1",
            "Speech": "",
            "SpeechConfidenceScore": "",
        }
    )

    assert webhook.digits == "1"
    assert webhook.input_type == "dtmf"
    assert webhook.speech is None
    assert webhook.speech_confidence is None


def test_spoken_gather_keeps_a_numeric_confidence_score() -> None:
    webhook = GatherWebhook.model_validate(
        {
            "CallUUID": "spoken-1",
            "From": "919325617129",
            "To": "+917971442643",
            "Direction": "inbound",
            "InputType": "speech",
            "Digits": "",
            "Speech": "Hindi",
            "SpeechConfidenceScore": "0.91",
        }
    )

    assert webhook.digits is None
    assert webhook.speech == "Hindi"
    assert webhook.speech_confidence == 0.91
