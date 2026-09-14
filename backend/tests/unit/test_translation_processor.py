"""The processor's own logic, with a fake translator - no network, no pipeline."""

from __future__ import annotations

from app.core.enums import Language, TranslationMode
from app.core.exceptions import TranslationFailedError
from app.pipeline.processors.translation import TranslationProcessor
from app.schemas.translation import TranslationRequest, TranslationResult


class FakeTranslator:
    """Implements ITranslator. Records what it was asked to translate."""

    def __init__(self, *, fail: bool = False) -> None:
        self.requests: list[TranslationRequest] = []
        self._fail = fail

    @property
    def name(self) -> str:
        return "fake"

    def supports(self, source: object, target: object) -> bool:
        return True

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        self.requests.append(request)
        if self._fail:
            raise TranslationFailedError("fake", "boom")
        return TranslationResult(
            text=f"[{request.target_language.value}] {request.text}",
            source_language=request.source_language,
            target_language=request.target_language,
            mode=request.mode,
            provider="fake",
            model="fake:v1",
            latency_ms=1.0,
        )


def make_processor(translator: FakeTranslator, *, max_chars: int = 1000) -> TranslationProcessor:
    return TranslationProcessor(
        translator=translator,
        source_language=Language.HINDI,
        target_language=Language.TAMIL,
        mode=TranslationMode.CODE_MIXED,
        max_chars=max_chars,
    )


async def test_translates_and_returns_target_text() -> None:
    translator = FakeTranslator()
    processor = make_processor(translator)

    spoken = await processor._translate("मुझे स्टेशन जाना है", sequence=1)

    assert spoken == "[ta-IN] मुझे स्टेशन जाना है"
    assert translator.requests[0].mode is TranslationMode.CODE_MIXED
    assert translator.requests[0].source_language is Language.HINDI


async def test_a_failed_translation_does_not_take_the_call_down() -> None:
    """One bad sentence costs the speaker a line, not the conversation."""
    processor = make_processor(FakeTranslator(fail=True))

    assert await processor._translate("anything", sequence=1) is None


def test_short_text_is_not_split() -> None:
    processor = make_processor(FakeTranslator())
    assert processor._split("one sentence") == ["one sentence"]


def test_long_text_splits_on_sentence_boundaries() -> None:
    """Breaks should land where the speaker paused, not mid-word."""
    processor = make_processor(FakeTranslator(), max_chars=30)
    chunks = processor._split("First part here. Second part here. Third part here.")

    assert all(len(c) <= 30 for c in chunks)
    assert chunks[0].endswith(".")
    assert "".join(chunks).replace(" ", "") == (
        "First part here.Second part here.Third part here.".replace(" ", "")
    )


def test_devanagari_danda_counts_as_a_sentence_end() -> None:
    """Hindi ends sentences with U+0964, not a period."""
    processor = make_processor(FakeTranslator(), max_chars=20)
    chunks = processor._split("पहला वाक्य। दूसरा वाक्य। तीसरा वाक्य।")

    assert all(len(c) <= 20 for c in chunks)
    assert chunks[0].endswith("।")


def test_a_single_oversized_sentence_is_hard_cut_rather_than_dropped() -> None:
    processor = make_processor(FakeTranslator(), max_chars=10)
    chunks = processor._split("x" * 35)

    assert all(len(c) <= 10 for c in chunks)
    assert "".join(chunks) == "x" * 35
