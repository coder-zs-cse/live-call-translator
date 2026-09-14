"""Calls and their legs.

A `Call` is one conversation. A `CallLeg` is one person's phone connection to
it. Two legs make a bridged call; a leg exists from the moment Vobiz hits the
answer webhook, long before pairing.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import CallStatus, Language, LegDirection, LegState, PairingMode
from app.models.base import Base, Timestamps, UUIDPrimaryKey


def _enum(enum_type: type, name: str) -> SAEnum:
    # native_enum=False keeps these as VARCHAR + CHECK, so adding a state is a
    # code change rather than a Postgres type migration.
    return SAEnum(enum_type, name=name, native_enum=False, length=32)


class Call(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "calls"

    room_code: Mapped[str | None] = mapped_column(String(8), index=True, nullable=True)
    pairing_mode: Mapped[PairingMode | None] = mapped_column(
        _enum(PairingMode, "pairing_mode"), nullable=True
    )
    status: Mapped[CallStatus] = mapped_column(
        _enum(CallStatus, "call_status"), default=CallStatus.PENDING, nullable=False
    )

    bridged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    legs: Mapped[list[CallLeg]] = relationship(back_populates="call", lazy="selectin")


class CallLeg(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "call_legs"

    call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), index=True, nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )

    #: Vobiz CallUUID. The correlation key across every webhook for this leg.
    provider_call_uuid: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    direction: Mapped[LegDirection] = mapped_column(_enum(LegDirection, "leg_direction"))
    phone_e164: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    state: Mapped[LegState] = mapped_column(
        _enum(LegState, "leg_state"), default=LegState.IDENTIFY, nullable=False
    )

    #: Snapshotted at bridge time. The user row may change later; what this call
    #: actually used must not.
    language_primary: Mapped[Language | None] = mapped_column(
        _enum(Language, "language"), nullable=True
    )
    language_secondary: Mapped[Language | None] = mapped_column(
        _enum(Language, "language"), nullable=True
    )

    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hangup_cause: Mapped[str | None] = mapped_column(String(64), nullable=True)

    call: Mapped[Call | None] = relationship(back_populates="legs")
