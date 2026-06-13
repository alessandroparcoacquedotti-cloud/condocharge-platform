from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from condocharge.api.v1.stations import _resolve_legrand_credentials, _stations_live_occupancy
from condocharge.app.services.email_service import EmailDeliveryError, EmailService
from condocharge.app.services.email_templates import (
    build_charging_completed_email,
    build_station_available_email,
)
from condocharge.core.config import Settings
from condocharge.models.charging import ChargingSession, ChargingStation
from condocharge.models.tenancy import (
    AppUser,
    AppUserRole,
    Condominium,
    ResidentEmailNotification,
    ResidentNotificationPreferences,
)

logger = logging.getLogger(__name__)

NOTIFICATION_TYPE_STATION_AVAILABLE = "station_available"
NOTIFICATION_TYPE_CHARGING_COMPLETED = "charging_completed"
STATUS_SENT = "sent"
STATUS_PREVIEW = "preview"
STATUS_FAILED = "failed"
NON_AVAILABLE_STATION_STATES = {"charging", "offline", "checking"}


@dataclass(frozen=True)
class StationAvailabilitySnapshot:
    station_id: int
    condominium_id: int
    computed_status: str
    observed_at: datetime


class LiveStationAvailabilityFetcher:
    def __call__(self, *, db: Session) -> Sequence[StationAvailabilitySnapshot]:
        stations = db.scalars(select(ChargingStation).order_by(ChargingStation.id.asc())).all()
        occupancy = _stations_live_occupancy(stations=stations, credentials=_resolve_legrand_credentials())

        return [
            StationAvailabilitySnapshot(
                station_id=station.id,
                condominium_id=station.condominium_id,
                computed_status=self._transition_status(
                    computed_status=item.computed_status,
                    connector_status=item.connector_status,
                ),
                observed_at=item.last_checked_at,
            )
            for station, item in zip(stations, occupancy, strict=True)
        ]

    @staticmethod
    def _transition_status(*, computed_status: str, connector_status: str | None) -> str:
        if computed_status != "available":
            return computed_status
        if connector_status in (None, "available"):
            return "available"
        return "checking"


class ResidentNotificationService:
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

    def list_station_available_residents(self, *, condominium_id: int) -> list[AppUser]:
        return list(
            self._db.scalars(
                select(AppUser)
                .outerjoin(ResidentNotificationPreferences, ResidentNotificationPreferences.app_user_id == AppUser.id)
                .where(AppUser.condominium_id == condominium_id)
                .where(AppUser.role == AppUserRole.RESIDENT.value)
                .where(AppUser.is_active == 1)
                .where(AppUser.email.is_not(None))
                .where(AppUser.email != "")
                .where(
                    or_(
                        ResidentNotificationPreferences.id.is_(None),
                        ResidentNotificationPreferences.station_available == 1,
                    )
                )
                .order_by(AppUser.id.asc())
            ).all()
        )

    def send_station_available(
        self,
        *,
        condominium_id: int,
        resident: AppUser,
        station: ChargingStation,
        observed_at: datetime,
        transition_key: str | None = None,
    ) -> ResidentEmailNotification | None:
        if not self._settings.notifications_enabled:
            return None
        recipient_email = self._normalized_email(resident.email)
        if recipient_email is None:
            return None
        if not self._resident_pref_enabled(
            resident_id=resident.id,
            notification_type=NOTIFICATION_TYPE_STATION_AVAILABLE,
        ):
            return None

        transition_key = transition_key or self._station_transition_key(
            station_id=station.id,
            observed_at=observed_at,
        )
        dedupe_key = f"{transition_key}:resident:{resident.id}"
        if self._station_cooldown_active(
            condominium_id=condominium_id,
            station_id=station.id,
            transition_key=transition_key,
            now=observed_at,
        ):
            return None
        if self._resident_station_available_cooldown_active(
            resident_id=resident.id,
            now=observed_at,
        ):
            return None

        template = build_station_available_email(
            condominium_name=self._condominium_name(condominium_id),
            resident_name=self._resident_name(resident),
            station_name=station.name or station.host,
            observed_at=self._as_utc(observed_at),
        )
        return self._deliver(
            condominium_id=condominium_id,
            resident_app_user_id=resident.id,
            recipient_email=recipient_email,
            notification_type=NOTIFICATION_TYPE_STATION_AVAILABLE,
            dedupe_key=dedupe_key,
            subject=template.subject,
            text_body=template.text_body,
            html_body=template.html_body,
        )

    def send_charging_completed(
        self,
        *,
        session: ChargingSession,
        resident: AppUser,
        station: ChargingStation,
    ) -> ResidentEmailNotification | None:
        if not self._settings.notifications_enabled:
            return None
        if session.end_time is None or not self._is_recent(session.end_time):
            return None

        recipient_email = self._normalized_email(resident.email)
        if recipient_email is None:
            return None
        if not self._resident_pref_enabled(
            resident_id=resident.id,
            notification_type=NOTIFICATION_TYPE_CHARGING_COMPLETED,
        ):
            return None

        template = build_charging_completed_email(
            condominium_name=self._condominium_name(session.condominium_id),
            resident_name=self._resident_name(resident),
            station_name=station.name or station.host,
            end_time=self._as_utc(session.end_time),
            energy_wh=session.energy_wh,
            total_minutes=session.total_minutes,
        )
        return self._deliver(
            condominium_id=session.condominium_id,
            resident_app_user_id=resident.id,
            recipient_email=recipient_email,
            notification_type=NOTIFICATION_TYPE_CHARGING_COMPLETED,
            dedupe_key=f"session:{session.id}",
            subject=template.subject,
            text_body=template.text_body,
            html_body=template.html_body,
        )

    def _deliver(
        self,
        *,
        condominium_id: int,
        resident_app_user_id: int,
        recipient_email: str,
        notification_type: str,
        dedupe_key: str,
        subject: str,
        text_body: str,
        html_body: str,
    ) -> ResidentEmailNotification | None:
        existing = self._existing_notification(
            condominium_id=condominium_id,
            notification_type=notification_type,
            dedupe_key=dedupe_key,
        )
        if existing is not None:
            return None

        now = datetime.now(tz=UTC)
        if not self._email_service.enabled:
            logger.info(
                "Preview resident notification type=%s condo=%s resident=%s dedupe_key=%s subject=%s",
                notification_type,
                condominium_id,
                resident_app_user_id,
                dedupe_key,
                subject,
            )
            return self._create_notification(
                condominium_id=condominium_id,
                resident_app_user_id=resident_app_user_id,
                notification_type=notification_type,
                dedupe_key=dedupe_key,
                status=STATUS_PREVIEW,
            )

        try:
            self._email_service.send(
                to_email=recipient_email,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
            )
        except EmailDeliveryError as exc:
            return self._create_notification(
                condominium_id=condominium_id,
                resident_app_user_id=resident_app_user_id,
                notification_type=notification_type,
                dedupe_key=dedupe_key,
                status=STATUS_FAILED,
                error_message=str(exc)[:1000],
            )

        return self._create_notification(
            condominium_id=condominium_id,
            resident_app_user_id=resident_app_user_id,
            notification_type=notification_type,
            dedupe_key=dedupe_key,
            status=STATUS_SENT,
            sent_at=now,
        )

    def _create_notification(
        self,
        *,
        condominium_id: int,
        resident_app_user_id: int,
        notification_type: str,
        dedupe_key: str,
        status: str,
        sent_at: datetime | None = None,
        error_message: str | None = None,
    ) -> ResidentEmailNotification:
        notification = ResidentEmailNotification(
            condominium_id=condominium_id,
            resident_app_user_id=resident_app_user_id,
            notification_type=notification_type,
            dedupe_key=dedupe_key,
            status=status,
            sent_at=sent_at,
            error_message=error_message,
        )
        self._db.add(notification)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self._existing_notification(
                condominium_id=condominium_id,
                notification_type=notification_type,
                dedupe_key=dedupe_key,
            )
            if existing is not None:
                return existing
            raise
        self._db.refresh(notification)
        return notification

    def _existing_notification(
        self,
        *,
        condominium_id: int,
        notification_type: str,
        dedupe_key: str,
    ) -> ResidentEmailNotification | None:
        return self._db.scalar(
            select(ResidentEmailNotification)
            .where(ResidentEmailNotification.condominium_id == condominium_id)
            .where(ResidentEmailNotification.notification_type == notification_type)
            .where(ResidentEmailNotification.dedupe_key == dedupe_key)
            .limit(1)
        )

    def _resident_pref_enabled(self, *, resident_id: int, notification_type: str) -> bool:
        preference_clause = (
            ResidentNotificationPreferences.station_available == 1
            if notification_type == NOTIFICATION_TYPE_STATION_AVAILABLE
            else ResidentNotificationPreferences.charging_completed == 1
        )
        return (
            self._db.scalar(
                select(AppUser.id)
                .outerjoin(ResidentNotificationPreferences, ResidentNotificationPreferences.app_user_id == AppUser.id)
                .where(AppUser.id == resident_id)
                .where(AppUser.role == AppUserRole.RESIDENT.value)
                .where(AppUser.is_active == 1)
                .where(or_(ResidentNotificationPreferences.id.is_(None), preference_clause))
                .limit(1)
            )
            is not None
        )

    def _station_cooldown_active(
        self,
        *,
        condominium_id: int,
        station_id: int,
        transition_key: str,
        now: datetime,
    ) -> bool:
        cutoff = now - timedelta(minutes=self._settings.notification_station_cooldown_minutes)
        return (
            self._db.scalar(
                select(ResidentEmailNotification.id)
                .where(ResidentEmailNotification.condominium_id == condominium_id)
                .where(ResidentEmailNotification.notification_type == NOTIFICATION_TYPE_STATION_AVAILABLE)
                .where(ResidentEmailNotification.created_at >= cutoff)
                .where(ResidentEmailNotification.dedupe_key.like(f"station:{station_id}:transition:%"))
                .where(not_(ResidentEmailNotification.dedupe_key.like(f"{transition_key}:resident:%")))
                .limit(1)
            )
            is not None
        )

    def _resident_station_available_cooldown_active(
        self,
        *,
        resident_id: int,
        now: datetime,
    ) -> bool:
        cutoff = now - timedelta(minutes=self._settings.notification_resident_cooldown_minutes)
        return (
            self._db.scalar(
                select(ResidentEmailNotification.id)
                .where(ResidentEmailNotification.resident_app_user_id == resident_id)
                .where(ResidentEmailNotification.notification_type == NOTIFICATION_TYPE_STATION_AVAILABLE)
                .where(ResidentEmailNotification.created_at >= cutoff)
                .limit(1)
            )
            is not None
        )

    def _is_recent(self, end_time: datetime) -> bool:
        return self._as_utc(end_time) >= datetime.now(tz=UTC) - timedelta(
            minutes=self._settings.notification_recency_minutes
        )

    def _condominium_name(self, condominium_id: int) -> str:
        condo = self._db.get(Condominium, condominium_id)
        if condo is None:
            return "CondoCharge"
        return condo.name

    @staticmethod
    def _station_transition_key(*, station_id: int, observed_at: datetime) -> str:
        return f"station:{station_id}:transition:{observed_at.isoformat()}"

    @staticmethod
    def _normalized_email(email: str | None) -> str | None:
        if email is None:
            return None
        value = email.strip()
        return value or None

    @staticmethod
    def _resident_name(resident: AppUser) -> str:
        full_name = " ".join(part for part in [resident.first_name, resident.last_name] if part and part.strip())
        return full_name or resident.username

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class StationAvailabilityNotificationPoller:
    def __init__(
        self,
        *,
        db_factory: Callable[[], Session],
        settings: Settings,
        occupancy_fetcher: Callable[..., Sequence[StationAvailabilitySnapshot]] | None = None,
    ) -> None:
        self._db_factory = db_factory
        self._settings = settings
        self._occupancy_fetcher = occupancy_fetcher or LiveStationAvailabilityFetcher()
        self._previous_statuses: dict[int, str] = {}

    def poll_once(self) -> int:
        if not self._settings.notifications_enabled:
            return 0

        with self._db_factory() as db:
            service = ResidentNotificationService(db=db, settings=self._settings)
            snapshots = list(self._occupancy_fetcher(db=db))
            created = 0

            for snapshot in snapshots:
                previous_status = self._previous_statuses.get(snapshot.station_id)
                self._previous_statuses[snapshot.station_id] = snapshot.computed_status
                if previous_status not in NON_AVAILABLE_STATION_STATES:
                    continue
                if snapshot.computed_status != "available":
                    continue

                station = db.get(ChargingStation, snapshot.station_id)
                if station is None:
                    continue

                transition_key = service._station_transition_key(
                    station_id=snapshot.station_id,
                    observed_at=snapshot.observed_at,
                )
                for resident in service.list_station_available_residents(
                    condominium_id=snapshot.condominium_id
                ):
                    notification = service.send_station_available(
                        condominium_id=snapshot.condominium_id,
                        resident=resident,
                        station=station,
                        observed_at=snapshot.observed_at,
                        transition_key=transition_key,
                    )
                    if notification is not None:
                        created += 1

            return created
