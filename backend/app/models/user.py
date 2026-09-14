"""A caller, identified by phone number.

There is no signup: the first inbound call creates the row, and the language
answers given then persist for every later call.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Language
from app.models.base import Base, Timestamps, UUIDPrimaryKey


class User(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "users"

    #: E.164, the only form we ever store. Normalisation happens at the edge.
    phone_e164: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)

    #: Null until the caller has answered the language questions. `None` is the
    #: signal that the IVR must ask, so it is not defaulted at the DB level.
    primary_language: Mapped[Language | None] = mapped_column(
        SAEnum(Language, name="language", native_enum=False, length=10), nullable=True
    )
    secondary_language: Mapped[Language | None] = mapped_column(
        SAEnum(Language, name="language", native_enum=False, length=10), nullable=True
    )

    last_call_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def has_language_preferences(self) -> bool:
        return self.primary_language is not None and self.secondary_language is not None
