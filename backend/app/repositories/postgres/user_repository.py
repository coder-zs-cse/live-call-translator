"""User persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Language
from app.core.exceptions import AppError
from app.models.base import utc_now
from app.models.user import User


class UserNotFoundError(AppError):
    pass


class PostgresUserRepository:
    """Implements IUserRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_phone(self, phone_e164: str) -> User | None:
        result = await self._session.execute(select(User).where(User.phone_e164 == phone_e164))
        return result.scalar_one_or_none()

    async def create(self, phone_e164: str) -> User:
        user = User(phone_e164=phone_e164)
        self._session.add(user)
        await self._session.flush()
        return user

    async def set_languages(
        self, user_id: uuid.UUID, *, primary: Language, secondary: Language
    ) -> User:
        user = await self._require(user_id)
        user.primary_language = primary
        user.secondary_language = secondary
        await self._session.flush()
        return user

    async def touch_last_call(self, user_id: uuid.UUID) -> None:
        user = await self._require(user_id)
        user.last_call_at = utc_now()
        await self._session.flush()

    async def _require(self, user_id: uuid.UUID) -> User:
        user = await self._session.get(User, user_id)
        if user is None:
            raise UserNotFoundError(f"no user {user_id}")
        return user
