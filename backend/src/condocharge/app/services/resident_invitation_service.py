from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from condocharge.app.services.email_service import EmailService
from condocharge.app.services.email_templates import build_resident_invitation_email
from condocharge.core.config import Settings
from condocharge.core.security import hash_password
from condocharge.models.tenancy import AppUser, Condominium, ResidentInvitationToken


INVITATION_EXPIRY_HOURS = 72


class InvitationError(Exception):
    pass


@dataclass(frozen=True)
class InvitationIssueResult:
    token: str
    invitation: ResidentInvitationToken
    expires_at: datetime


@dataclass(frozen=True)
class InvitationLookupResult:
    valid: bool
    username: str | None = None
    condominium_name: str | None = None
    expires_at: datetime | None = None
    resident: AppUser | None = None
    invitation: ResidentInvitationToken | None = None


class ResidentInvitationService:
    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        email_service: EmailService | None = None,
    ) -> None:
        self._db = db
        self._settings = settings
        self._email_service = email_service or EmailService(settings=settings)

    def issue_invitation(
        self,
        *,
        resident: AppUser,
        condominium: Condominium,
        created_by_admin: AppUser,
        commit: bool = True,
    ) -> InvitationIssueResult:
        if not resident.email:
            raise InvitationError("Resident email is required before sending an invitation")
        if not self._email_service.enabled:
            raise InvitationError("SMTP email delivery is disabled")
        public_url = self._settings.public_url.strip().rstrip("/")
        if not public_url:
            raise InvitationError("CONDOCHARGE_PUBLIC_URL must be configured before sending invitations")

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=INVITATION_EXPIRY_HOURS)
        invitation = ResidentInvitationToken(
            app_user_id=resident.id,
            token_hash=self._hash_token(token),
            expires_at=expires_at,
            created_by_admin_id=created_by_admin.id,
        )
        self._db.add(invitation)
        self._db.flush()

        template = build_resident_invitation_email(
            condominium_name=condominium.name,
            username=resident.username,
            invitation_link=f"{public_url}/invite/{token}",
            expires_at=expires_at,
        )
        self._email_service.send(
            to_email=resident.email,
            subject=template.subject,
            text_body=template.text_body,
            html_body=template.html_body,
        )

        if commit:
            self._db.commit()
            self._db.refresh(invitation)

        return InvitationIssueResult(token=token, invitation=invitation, expires_at=expires_at)

    def get_invitation(self, *, token: str) -> InvitationLookupResult:
        now = datetime.now(tz=timezone.utc)
        invitation = self._db.scalar(
            select(ResidentInvitationToken)
            .where(ResidentInvitationToken.token_hash == self._hash_token(token))
            .order_by(ResidentInvitationToken.id.desc())
            .limit(1)
        )
        if invitation is None:
            return InvitationLookupResult(valid=False)

        resident = self._db.get(AppUser, invitation.app_user_id)
        if resident is None:
            return InvitationLookupResult(valid=False)

        condominium = self._db.get(Condominium, resident.condominium_id)
        if condominium is None:
            return InvitationLookupResult(valid=False)

        expires_at = self._as_utc(invitation.expires_at)
        if invitation.used_at is not None or expires_at <= now:
            return InvitationLookupResult(valid=False)

        newest_valid = self._db.scalar(
            select(ResidentInvitationToken)
            .where(ResidentInvitationToken.app_user_id == resident.id)
            .where(ResidentInvitationToken.used_at.is_(None))
            .where(ResidentInvitationToken.expires_at > now.replace(tzinfo=None))
            .order_by(ResidentInvitationToken.created_at.desc(), ResidentInvitationToken.id.desc())
            .limit(1)
        )
        if newest_valid is None or newest_valid.id != invitation.id:
            return InvitationLookupResult(valid=False)

        return InvitationLookupResult(
            valid=True,
            username=resident.username,
            condominium_name=condominium.name,
            expires_at=expires_at,
            resident=resident,
            invitation=invitation,
        )

    def complete_invitation(self, *, token: str, password: str) -> InvitationLookupResult:
        lookup = self.get_invitation(token=token)
        if not lookup.valid or lookup.resident is None or lookup.invitation is None:
            raise InvitationError("Invitation token is invalid or expired")
        if self._resident_was_disabled_after_invitation(resident=lookup.resident, invitation=lookup.invitation):
            raise InvitationError("Invitation token is invalid or expired")

        lookup.resident.password_hash = hash_password(password)
        lookup.resident.must_change_password = 0
        lookup.resident.token_version = int(getattr(lookup.resident, "token_version", 0) or 0) + 1
        if not lookup.resident.is_active:
            lookup.resident.is_active = 1
        lookup.invitation.used_at = datetime.now(tz=timezone.utc)
        self._db.commit()
        self._db.refresh(lookup.resident)
        self._db.refresh(lookup.invitation)
        return lookup

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _resident_was_disabled_after_invitation(cls, *, resident: AppUser, invitation: ResidentInvitationToken) -> bool:
        if resident.is_active:
            return False
        updated_at = getattr(resident, "updated_at", None)
        if updated_at is None:
            return False
        return cls._as_utc(updated_at) > cls._as_utc(invitation.created_at)
