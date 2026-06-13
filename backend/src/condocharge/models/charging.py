from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from condocharge.db.base import Base

if TYPE_CHECKING:
    from condocharge.models.tenancy import AppUser


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
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
