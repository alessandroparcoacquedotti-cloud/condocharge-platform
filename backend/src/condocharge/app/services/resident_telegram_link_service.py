from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from condocharge.core.config import Settings
from condocharge.models.tenancy import AppUser, ResidentTelegramLinkToken


class TelegramLinkError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramLinkIssue:
    token: str
    expires_at: datetime
    deep_link_url: str | None


class ResidentTelegramLinkService:
    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        deep_link_builder: Callable[[str], str | None] | None = None,
    ) -> None:
        self._db = db
        self._settings = settings
        self._deep_link_builder = deep_link_builder

    def issue_link(self, *, resident: AppUser, commit: bool = True) -> TelegramLinkIssue:
        if resident.role != "resident":
            raise TelegramLinkError("Telegram linking is only available for residents.")

        token = secrets.token_urlsafe(24)
        expires_at = datetime.now(tz=UTC) + timedelta(minutes=self._settings.telegram_link_token_ttl_minutes)
        record = ResidentTelegramLinkToken(
            app_user_id=resident.id,
            token_hash=self._hash_token(token),
            expires_at=expires_at,
        )
        self._db.add(record)
        if commit:
            self._db.commit()
            self._db.refresh(record)
        deep_link_url = self._deep_link_builder(token) if self._deep_link_builder is not None else None
        return TelegramLinkIssue(token=token, expires_at=expires_at, deep_link_url=deep_link_url)

    def link_chat(
        self,
        *,
        token: str,
        chat_id: str,
        telegram_username: str | None,
    ) -> AppUser:
        now = datetime.now(tz=UTC)
        record = self._db.scalar(
            select(ResidentTelegramLinkToken)
            .where(ResidentTelegramLinkToken.token_hash == self._hash_token(token))
            .order_by(ResidentTelegramLinkToken.created_at.desc(), ResidentTelegramLinkToken.id.desc())
            .limit(1)
        )
        if record is None or record.used_at is not None or self._as_utc(record.expires_at) < now:
            raise TelegramLinkError("Telegram link token is invalid or expired.")

        resident = self._db.get(AppUser, record.app_user_id)
        if resident is None or resident.role != "resident" or not resident.is_active:
            raise TelegramLinkError("Resident account is not available for Telegram linking.")

        existing = self._db.scalar(select(AppUser).where(AppUser.telegram_chat_id == chat_id).limit(1))
        if existing is not None and existing.id != resident.id:
            existing.telegram_chat_id = None
            existing.telegram_username = None
            existing.telegram_linked_at = None

        resident.telegram_chat_id = chat_id
        resident.telegram_username = telegram_username
        resident.telegram_linked_at = now
        record.used_at = now
        self._db.commit()
        self._db.refresh(resident)
        return resident

    def unlink(self, *, resident: AppUser) -> AppUser:
        resident.telegram_chat_id = None
        resident.telegram_username = None
        resident.telegram_linked_at = None
        self._db.commit()
        self._db.refresh(resident)
        return resident

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
