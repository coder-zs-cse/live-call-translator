"""DI wiring: interfaces to concrete implementations.

The only module that knows both sides. Routers ask for a service and get one
assembled from whatever this file decided, which is what makes the API layer
testable without a network or a database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.ivr.prompt_service import PromptService
from app.providers.interfaces import ITextToSpeech, ITranslator
from app.providers.registry import ProviderBundle
from app.repositories.postgres.call_repository import (
    PostgresCallLegRepository,
    PostgresCallRepository,
)
from app.repositories.postgres.session import session_scope
from app.repositories.postgres.user_repository import PostgresUserRepository
from app.repositories.redis.room_registry import RedisRoomRegistry
from app.services.ivr_service import IvrService
from app.services.pairing_service import PairingService
from app.telephony.vobiz.client import VobizClient

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One transaction per request, committed when the handler returns.

    A webhook that raises leaves no half-written leg behind.
    """
    async for session in session_scope(request.app.state.session_factory):
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


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


def get_telephony(request: Request) -> VobizClient:
    client: VobizClient = request.app.state.telephony
    return client


def get_prompt_service() -> PromptService:
    return PromptService()


def get_ivr_service(
    session: SessionDep,
    settings: SettingsDep,
    redis: Annotated[Redis, Depends(get_redis)],
    prompts: Annotated[PromptService, Depends(get_prompt_service)],
) -> IvrService:
    calls = PostgresCallRepository(session)
    legs = PostgresCallLegRepository(session)
    rooms = RedisRoomRegistry(redis, redis_settings=settings.redis, call_settings=settings.call)
    return IvrService(
        users=PostgresUserRepository(session),
        legs=legs,
        pairing=PairingService(calls=calls, legs=legs, rooms=rooms),
        prompts=prompts,
        call_settings=settings.call,
    )


TranslatorDep = Annotated[ITranslator, Depends(get_translator)]
TextToSpeechDep = Annotated[ITextToSpeech, Depends(get_text_to_speech)]
TelephonyDep = Annotated[VobizClient, Depends(get_telephony)]
IvrServiceDep = Annotated[IvrService, Depends(get_ivr_service)]
