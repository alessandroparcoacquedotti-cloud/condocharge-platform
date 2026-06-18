from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from condocharge.db.base import Base

if TYPE_CHECKING:
    from condocharge.models.tenancy import AppUser


class UtcAwareDateTime(TypeDecorator[datetime]):
    """Store timestamps as ISO-8601 UTC strings and always return aware UTC datetimes."""

    impl = String(64)
    cache_ok = True

    @staticmethod
    def _coerce(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_bind_param(self, value: datetime | None, dialect: object) -> str | None:
        del dialect
        if value is None:
            return None
        return self._coerce(value).isoformat().replace("+00:00", "Z")

    def process_result_value(self, value: object, dialect: object) -> datetime | None:
        del dialect
        if value is None:
            return None
        if isinstance(value, datetime):
            return self._coerce(value)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return self._coerce(parsed)


class ChargingStation(Base):
    __tablename__ = "charging_stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condominium_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("condominiums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    host: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    vendor: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="unknown")
    status_source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="last_sync")
    last_sync_at: Mapped[datetime | None] = mapped_column(UtcAwareDateTime(), nullable=True)

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    connector_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rfid_enabled: Mapped[bool | None] = mapped_column(Boolean(), nullable=True)
    charging_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_status_payload_json: Mapped[str | None] = mapped_column(Text(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    sessions: Mapped[list[ChargingSession]] = relationship(
        back_populates="station",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RfidUser(Base):
    __tablename__ = "rfid_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condominium_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("condominiums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    app_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("app_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rfid_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    sessions: Mapped[list[ChargingSession]] = relationship(
        back_populates="rfid_user",
        passive_deletes=True,
    )
    app_user: Mapped[AppUser | None] = relationship(back_populates="rfid_users")


class ChargingSession(Base):
    __tablename__ = "charging_sessions"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_charging_sessions_source_key"),
        UniqueConstraint("station_id", "start_time", "end_time", "energy_wh", name="uq_session_natural_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    condominium_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("condominiums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)

    station_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("charging_stations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rfid_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("rfid_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    energy_wh: Mapped[int] = mapped_column(Integer, nullable=False)

    total_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    charging_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    idle_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    plug_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    station: Mapped[ChargingStation] = relationship(back_populates="sessions")
    rfid_user: Mapped[RfidUser | None] = relationship(back_populates="sessions")
