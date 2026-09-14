"""Test fixtures.

The important one is `pinned_pipeline_mode`: without it, whichever
`PIPELINE__MODE` happens to be in `.env.local` decides what the integration
tests exercise, so flipping a config value silently sends the echo test through
the translation pipeline - and straight into a live Sarvam websocket. Tests
assert on what they name, not on developer config.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.core.config import get_settings
from app.core.enums import PipelineMode


@pytest.fixture
def pipeline_mode(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[PipelineMode]:
    """Force a pipeline mode for the duration of one test.

    Real environment variables outrank the env file in pydantic-settings, so
    setting one and clearing the settings cache is enough.
    """
    mode: PipelineMode = getattr(request, "param", PipelineMode.ECHO)

    monkeypatch.setenv("PIPELINE__MODE", mode.value)
    get_settings.cache_clear()
    try:
        yield mode
    finally:
        # Undo before the next test reads a stale cached Settings.
        monkeypatch.undo()
        get_settings.cache_clear()
