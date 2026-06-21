from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from condocharge.db.base import Base

QUEUE_ENTRY_STATUS_WAITING = "waiting"
QUEUE_ENTRY_STATUS_OFFERED = "offered"
QUEUE_ENTRY_STATUS_LEFT = "left"


class ChargingQueueSettings(Base):
    __tablename__ = "charging_queue_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condominium_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("condominiums.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    queue_enabled: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ChargingQueueEntry(Base):
    __tablename__ = "charging_queue_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condominium_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("condominiums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resident_app_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reserved_station_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("charging_stations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=QUEUE_ENTRY_STATUS_WAITING)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reservation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    leave_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
