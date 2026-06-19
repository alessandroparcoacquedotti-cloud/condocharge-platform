from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from condocharge.db.base import Base
from condocharge.models.billing import BillingPeriod, ResidentBillingStatement

if TYPE_CHECKING:
    from condocharge.models.charging import RfidUser


class AppUserRole(StrEnum):
    ADMIN = "admin"
    RESIDENT = "resident"
    VIEWER = "viewer"


class Condominium(Base):
    __tablename__ = "condominiums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    energy_price_eur_per_kwh: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, server_default="0.30")
    telegram_station_available_enabled: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    telegram_charging_completed_enabled: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    telegram_agent_offline_enabled: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    telegram_agent_recovered_enabled: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    users: Mapped[list[AppUser]] = relationship(
        back_populates="condominium",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    billing_periods: Mapped[list[BillingPeriod]] = relationship(
        back_populates="condominium",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AppUser(Base):
    __tablename__ = "app_users"
    __table_args__ = (
        UniqueConstraint("condominium_id", "username", name="uq_app_users_condo_username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condominium_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("condominiums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    apartment_or_unit: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    must_change_password: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    condominium: Mapped[Condominium] = relationship(back_populates="users")
    rfid_users: Mapped[list[RfidUser]] = relationship(
        back_populates="app_user",
        passive_deletes=True,
    )
    billing_statements: Mapped[list[ResidentBillingStatement]] = relationship(
        back_populates="resident",
        passive_deletes=True,
    )


class ResidentNotificationPreferences(Base):
    __tablename__ = "resident_notification_preferences"
    __table_args__ = (
        UniqueConstraint("app_user_id", name="uq_resident_notification_preferences_app_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condominium_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("condominiums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    app_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    charging_completed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    station_available: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    station_back_online: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    agent_offline: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    agent_recovered: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    resident: Mapped[AppUser] = relationship()


class ResidentEmailNotification(Base):
    __tablename__ = "resident_email_notifications"
    __table_args__ = (
        UniqueConstraint(
            "condominium_id",
            "notification_type",
            "dedupe_key",
            name="uq_resident_email_notifications_dedupe",
        ),
    )

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
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    resident: Mapped[AppUser] = relationship()


class ResidentNotificationHistory(Base):
    __tablename__ = "resident_notification_history"
    __table_args__ = (
        UniqueConstraint(
            "condominium_id",
            "channel",
            "notification_type",
            "dedupe_key",
            name="uq_resident_notification_history_dedupe",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condominium_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("condominiums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resident_app_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("app_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    resident: Mapped[AppUser | None] = relationship()


class ResidentTelegramLinkToken(Base):
    __tablename__ = "resident_telegram_link_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_resident_telegram_link_tokens_token_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    app_user: Mapped[AppUser] = relationship()


class ResidentInvitationToken(Base):
    __tablename__ = "resident_invitation_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_resident_invitation_tokens_token_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_admin_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    app_user: Mapped[AppUser] = relationship(foreign_keys=[app_user_id])
    created_by_admin: Mapped[AppUser] = relationship(foreign_keys=[created_by_admin_id])
