"""DI wiring: interfaces to concrete implementations.

The only module that knows both sides. Routers ask for an interface and get
whatever this file decided to build, which is what makes the API layer testable
without a network.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.providers.interfaces import ITextToSpeech, ITranslator
from app.providers.registry import ProviderBundle

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_provider_bundle(request: Request) -> ProviderBundle:
    """Built once at startup and held on app state, so the HTTP pool is shared."""
    bundle: ProviderBundle = request.app.state.providers
    return bundle


def get_translator(
    bundle: Annotated[ProviderBundle, Depends(get_provider_bundle)],
) -> ITranslator:
    return bundle.translator


def get_text_to_speech(
    bundle: Annotated[ProviderBundle, Depends(get_provider_bundle)],
) -> ITextToSpeech:
    return bundle.text_to_speech


TranslatorDep = Annotated[ITranslator, Depends(get_translator)]
TextToSpeechDep = Annotated[ITextToSpeech, Depends(get_text_to_speech)]
