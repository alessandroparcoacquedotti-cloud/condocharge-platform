from __future__ import annotations

# mypy: disable-error-code=import-untyped
import hashlib
import json
import logging
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from pywebpush import WebPushException, webpush
from sqlalchemy import not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from condocharge.app.services.queue_service import QueueService
from condocharge.app.services.resident_notification_service import (
    NOTIFICATION_TYPE_CHARGING_COMPLETED,
    NOTIFICATION_TYPE_STATION_AVAILABLE,
    LiveStationAvailabilityFetcher,
    StationAvailabilitySnapshot,
)
from condocharge.app.services.telegram_notification_service import NOTIFICATION_TYPE_AGENT_OFFLINE
from condocharge.core.config import Settings
from condocharge.models.charging import AgentState, ChargingSession, ChargingStation
from condocharge.models.queue import (
    QUEUE_ENTRY_STATUS_OFFERED,
    QUEUE_ENTRY_STATUS_WAITING,
    ChargingQueueEntry,
)
from condocharge.models.tenancy import (
    AppUser,
    AppUserRole,
    PushSubscription,
    ResidentNotificationHistory,
    ResidentNotificationPreferences,
)

CHANNEL_WEB_PUSH = "web_push"
STATUS_SENT = "sent"
STATUS_PREVIEW = "preview"
STATUS_FAILED = "failed"
STATUS_NOT_SUBSCRIBED = "not_subscribed"
NOTIFICATION_TYPE_PUSH_TEST = "push_test"
NOTIFICATION_TYPE_QUEUE_NEXT_IN_LINE = "queue_next_in_line"
_BUSY_STATES = {"busy", "charging", "occupied"}
_AVAILABLE_STATES = {"available", "free"}
_UNAVAILABLE_STATES = {"unavailable", "offline", "faulted", "unknown", "unreachable", "degraded"}
_ONLINE_TRANSITION_STATES = {"checking", *_UNAVAILABLE_STATES}
_ROME_TZ = ZoneInfo("Europe/Rome")
_LOG = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class PushDeliveryResult:
    status: str
    delivered_count: int


class PushNotificationService:
    def __init__(self, *, db: Session, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def subscription_status(self, *, user: AppUser) -> tuple[bool, int]:
        active_count = len(self._active_subscriptions_for_user(user_id=user.id))
        return active_count > 0, active_count

    def upsert_subscription(
        self,
        *,
        user: AppUser,
        endpoint: str,
        p256dh: str,
        auth: str,
    ) -> tuple[bool, int]:
        row = self._db.scalar(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint).limit(1)
        )
        if row is None:
            row = PushSubscription(
                user_id=user.id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                active=1,
            )
            self._db.add(row)
        else:
            row.user_id = user.id
            row.endpoint = endpoint
            row.p256dh = p256dh
            row.auth = auth
            row.active = 1
        self._db.commit()
        return self.subscription_status(user=user)

    def deactivate_subscription(self, *, user: AppUser, endpoint: str) -> tuple[bool, int]:
        row = self._db.scalar(
            select(PushSubscription)
            .where(PushSubscription.user_id == user.id)
            .where(PushSubscription.endpoint == endpoint)
            .limit(1)
        )
        if row is not None:
            row.active = 0
            self._db.commit()
        return self.subscription_status(user=user)

    def send_test(self, *, user: AppUser) -> PushDeliveryResult:
        subscribed, active_count = self.subscription_status(user=user)
        if not subscribed:
            return PushDeliveryResult(status=STATUS_NOT_SUBSCRIBED, delivered_count=0)
        preview = {
            "title": "Test notifiche CondoCharge",
            "body": "Notifica push inviata correttamente al tuo dispositivo.",
            "url": self._default_url_for_user(user),
            "tag": f"push-test-{user.id}",
        }
        delivered = self._deliver_to_user(
            condominium_id=user.condominium_id,
            user=user,
            notification_type=NOTIFICATION_TYPE_PUSH_TEST,
            dedupe_key=f"push-test:{user.id}:{datetime.now(tz=UTC).isoformat()}",
            payload=preview,
        )
        if delivered > 0 and self._settings.web_push_enabled:
            return PushDeliveryResult(status=STATUS_SENT, delivered_count=delivered)
        if delivered > 0:
            return PushDeliveryResult(status=STATUS_PREVIEW, delivered_count=delivered)
        return PushDeliveryResult(
            status=STATUS_FAILED if active_count > 0 else STATUS_NOT_SUBSCRIBED, delivered_count=0
        )

    def list_subscribed_residents(
        self, *, condominium_id: int, notification_type: str
    ) -> list[AppUser]:
        query = (
            select(AppUser)
            .join(PushSubscription, PushSubscription.user_id == AppUser.id)
            .outerjoin(
                ResidentNotificationPreferences,
                ResidentNotificationPreferences.app_user_id == AppUser.id,
            )
            .where(AppUser.condominium_id == condominium_id)
            .where(AppUser.role == AppUserRole.RESIDENT.value)
            .where(AppUser.is_active == 1)
            .where(PushSubscription.active == 1)
        )
        preference_clause = self._resident_preference_clause(notification_type=notification_type)
        if preference_clause is not None:
            query = query.where(
                or_(ResidentNotificationPreferences.id.is_(None), preference_clause)
            )
        return list(self._db.scalars(query.order_by(AppUser.id.asc()).distinct()).all())

    def list_subscribed_admins(self, *, condominium_id: int) -> list[AppUser]:
        query = (
            select(AppUser)
            .join(PushSubscription, PushSubscription.user_id == AppUser.id)
            .where(AppUser.condominium_id == condominium_id)
            .where(AppUser.role == AppUserRole.ADMIN.value)
            .where(AppUser.is_active == 1)
            .where(PushSubscription.active == 1)
            .order_by(AppUser.id.asc())
            .distinct()
        )
        return list(self._db.scalars(query).all())

    def send_station_available(
        self,
        *,
        condominium_id: int,
        resident: AppUser,
        station: ChargingStation,
        observed_at: datetime,
        transition_key: str | None = None,
    ) -> int:
        if not self._settings.notifications_enabled:
            return 0
        transition_key = transition_key or self._station_transition_key(
            station_id=station.id,
            observed_at=observed_at,
        )
        if self._station_cooldown_active(
            condominium_id=condominium_id,
            station_id=station.id,
            transition_key=transition_key,
            now=observed_at,
        ):
            return 0
        if self._resident_station_available_cooldown_active(
            resident_id=resident.id, now=observed_at
        ):
            return 0
        return self._deliver_to_user(
            condominium_id=condominium_id,
            user=resident,
            notification_type=NOTIFICATION_TYPE_STATION_AVAILABLE,
            dedupe_key=f"{transition_key}:resident:{resident.id}",
            payload={
                "title": "Colonnina disponibile",
                "body": f"La postazione {station.name or station.host} e pronta per essere utilizzata.",
                "url": "/resident/stato-colonnine",
                "tag": f"station-available-{station.id}",
            },
        )

    def send_charging_completed(
        self,
        *,
        session: ChargingSession,
        resident: AppUser,
        station: ChargingStation,
    ) -> int:
        if not self._settings.notifications_enabled:
            return 0
        if session.end_time is None or not self._is_recent(session.end_time):
            return 0
        return self._deliver_to_user(
            condominium_id=session.condominium_id,
            user=resident,
            notification_type=NOTIFICATION_TYPE_CHARGING_COMPLETED,
            dedupe_key=f"session:{session.id}:resident:{resident.id}",
            payload={
                "title": "Ricarica completata",
                "body": f"La tua ricarica su {station.name or station.host} e terminata. Ti chiediamo di liberare il posto.",
                "url": "/resident/ricariche",
                "tag": f"charging-completed-{session.id}",
            },
        )

    def send_queue_next_in_line(
        self,
        *,
        condominium_id: int,
        resident: AppUser,
        entry_id: int,
    ) -> int:
        if not self._settings.notifications_enabled:
            return 0
        return self._deliver_to_user(
            condominium_id=condominium_id,
            user=resident,
            notification_type=NOTIFICATION_TYPE_QUEUE_NEXT_IN_LINE,
            dedupe_key=f"queue-entry:{entry_id}:next-in-line",
            payload={
                "title": "Sei il prossimo in coda",
                "body": "Preparati a raggiungere la postazione.",
                "url": "/resident/stato-colonnine",
                "tag": f"queue-next-{entry_id}",
            },
        )

    def send_agent_offline(
        self,
        *,
        condominium_id: int,
        admin_user: AppUser,
        agent_state: AgentState,
        detected_at: datetime,
    ) -> int:
        if not self._settings.notifications_enabled:
            return 0
        return self._deliver_to_user(
            condominium_id=condominium_id,
            user=admin_user,
            notification_type=NOTIFICATION_TYPE_AGENT_OFFLINE,
            dedupe_key=f"agent:{agent_state.agent_id}:offline:{self._as_utc(detected_at).isoformat()}",
            payload={
                "title": "Agente offline",
                "body": f"L'agente {agent_state.agent_id} non sta inviando aggiornamenti.",
                "url": "/admin/panoramica",
                "tag": f"agent-offline-{agent_state.agent_id}",
            },
        )

    def _deliver_to_user(
        self,
        *,
        condominium_id: int,
        user: AppUser,
        notification_type: str,
        dedupe_key: str,
        payload: dict[str, str],
    ) -> int:
        subscriptions = self._active_subscriptions_for_user(user_id=user.id)
        if not subscriptions:
            return 0

        _LOG.info(
            "push subscription found user_id=%s notification_type=%s active_subscriptions=%s",
            user.id,
            notification_type,
            len(subscriptions),
        )
        delivered = 0
        for subscription in subscriptions:
            subscription_key = self._subscription_key(subscription.endpoint)
            subscription_dedupe_key = (
                f"{dedupe_key}:subscription:{subscription_key}"
            )
            if (
                self._existing_notification(
                    condominium_id=condominium_id,
                    notification_type=notification_type,
                    dedupe_key=subscription_dedupe_key,
                )
                is not None
            ):
                continue

            _LOG.info(
                "push delivery attempt user_id=%s notification_type=%s subscription_key=%s dedupe_key=%s",
                user.id,
                notification_type,
                subscription_key,
                subscription_dedupe_key,
            )
            if not self._settings.web_push_enabled:
                self._create_history(
                    condominium_id=condominium_id,
                    user_id=user.id,
                    recipient=subscription.endpoint,
                    notification_type=notification_type,
                    dedupe_key=subscription_dedupe_key,
                    status=STATUS_PREVIEW,
                )
                _LOG.info(
                    "push provider response user_id=%s notification_type=%s subscription_key=%s status=%s",
                    user.id,
                    notification_type,
                    subscription_key,
                    STATUS_PREVIEW,
                )
                _LOG.info(
                    "push sent user_id=%s notification_type=%s subscription_key=%s delivery_status=%s",
                    user.id,
                    notification_type,
                    subscription_key,
                    STATUS_PREVIEW,
                )
                delivered += 1
                continue

            try:
                response = webpush(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": {
                            "p256dh": subscription.p256dh,
                            "auth": subscription.auth,
                        },
                    },
                    data=json.dumps(payload, ensure_ascii=False),
                    vapid_private_key=self._settings.web_push_vapid_private_key.strip(),
                    vapid_claims={"sub": self._settings.web_push_vapid_subject.strip()},
                    ttl=max(int(self._settings.web_push_ttl_seconds), 60),
                )
            except WebPushException as exc:
                if self._is_gone(exc):
                    self._mark_subscription_inactive(subscription=subscription)
                response = getattr(exc, "response", None)
                provider_status = getattr(response, "status_code", None)
                _LOG.warning(
                    "push provider response user_id=%s notification_type=%s subscription_key=%s status=%s error=%s",
                    user.id,
                    notification_type,
                    subscription_key,
                    provider_status,
                    str(exc)[:300],
                )
                self._create_history(
                    condominium_id=condominium_id,
                    user_id=user.id,
                    recipient=subscription.endpoint,
                    notification_type=notification_type,
                    dedupe_key=subscription_dedupe_key,
                    status=STATUS_FAILED,
                    error_message=str(exc)[:1000],
                )
                continue

            provider_status = str(getattr(response, "status_code", "")) or None
            _LOG.info(
                "push provider response user_id=%s notification_type=%s subscription_key=%s status=%s",
                user.id,
                notification_type,
                subscription_key,
                provider_status or "",
            )
            self._create_history(
                condominium_id=condominium_id,
                user_id=user.id,
                recipient=subscription.endpoint,
                notification_type=notification_type,
                dedupe_key=subscription_dedupe_key,
                status=STATUS_SENT,
                sent_at=datetime.now(tz=UTC),
                provider_message_id=provider_status,
            )
            _LOG.info(
                "push sent user_id=%s notification_type=%s subscription_key=%s delivery_status=%s",
                user.id,
                notification_type,
                subscription_key,
                STATUS_SENT,
            )
            delivered += 1
        return delivered

    def _create_history(
        self,
        *,
        condominium_id: int,
        user_id: int | None,
        recipient: str,
        notification_type: str,
        dedupe_key: str,
        status: str,
        sent_at: datetime | None = None,
        provider_message_id: str | None = None,
        error_message: str | None = None,
    ) -> ResidentNotificationHistory:
        row = ResidentNotificationHistory(
            condominium_id=condominium_id,
            resident_app_user_id=user_id,
            channel=CHANNEL_WEB_PUSH,
            recipient=recipient,
            notification_type=notification_type,
            dedupe_key=dedupe_key,
            status=status,
            sent_at=sent_at,
            provider_message_id=provider_message_id,
            error_message=error_message,
        )
        self._db.add(row)
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
        self._db.refresh(row)
        return row

    def _existing_notification(
        self,
        *,
        condominium_id: int,
        notification_type: str,
        dedupe_key: str,
    ) -> ResidentNotificationHistory | None:
        return self._db.scalar(
            select(ResidentNotificationHistory)
            .where(ResidentNotificationHistory.condominium_id == condominium_id)
            .where(ResidentNotificationHistory.channel == CHANNEL_WEB_PUSH)
            .where(ResidentNotificationHistory.notification_type == notification_type)
            .where(ResidentNotificationHistory.dedupe_key == dedupe_key)
            .limit(1)
        )

    def _active_subscriptions_for_user(self, *, user_id: int) -> list[PushSubscription]:
        return list(
            self._db.scalars(
                select(PushSubscription)
                .where(PushSubscription.user_id == user_id)
                .where(PushSubscription.active == 1)
                .order_by(PushSubscription.id.asc())
            ).all()
        )

    def _mark_subscription_inactive(self, *, subscription: PushSubscription) -> None:
        subscription.active = 0
        self._db.commit()

    @staticmethod
    def _subscription_key(endpoint: str) -> str:
        return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _is_gone(exc: WebPushException) -> bool:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        return status_code in {404, 410}

    def _resident_preference_clause(self, *, notification_type: str) -> ColumnElement[bool] | None:
        mapping: dict[str, ColumnElement[bool]] = {
            NOTIFICATION_TYPE_STATION_AVAILABLE: ResidentNotificationPreferences.station_available
            == 1,
            NOTIFICATION_TYPE_CHARGING_COMPLETED: ResidentNotificationPreferences.charging_completed
            == 1,
            NOTIFICATION_TYPE_QUEUE_NEXT_IN_LINE: ResidentNotificationPreferences.station_available
            == 1,
        }
        return mapping.get(notification_type)

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
                select(ResidentNotificationHistory.id)
                .where(ResidentNotificationHistory.condominium_id == condominium_id)
                .where(ResidentNotificationHistory.channel == CHANNEL_WEB_PUSH)
                .where(
                    ResidentNotificationHistory.notification_type
                    == NOTIFICATION_TYPE_STATION_AVAILABLE
                )
                .where(ResidentNotificationHistory.created_at >= cutoff)
                .where(
                    ResidentNotificationHistory.dedupe_key.like(
                        f"station:{station_id}:transition:%"
                    )
                )
                .where(
                    not_(
                        ResidentNotificationHistory.dedupe_key.like(f"{transition_key}:resident:%")
                    )
                )
                .limit(1)
            )
            is not None
        )

    def _resident_station_available_cooldown_active(
        self, *, resident_id: int, now: datetime
    ) -> bool:
        cutoff = now - timedelta(minutes=self._settings.notification_resident_cooldown_minutes)
        return (
            self._db.scalar(
                select(ResidentNotificationHistory.id)
                .where(ResidentNotificationHistory.resident_app_user_id == resident_id)
                .where(ResidentNotificationHistory.channel == CHANNEL_WEB_PUSH)
                .where(
                    ResidentNotificationHistory.notification_type
                    == NOTIFICATION_TYPE_STATION_AVAILABLE
                )
                .where(ResidentNotificationHistory.created_at >= cutoff)
                .limit(1)
            )
            is not None
        )

    def _default_url_for_user(self, user: AppUser) -> str:
        if user.role == AppUserRole.ADMIN.value:
            return "/admin/impostazioni"
        return "/resident/profilo"

    @staticmethod
    def _station_transition_key(*, station_id: int, observed_at: datetime) -> str:
        return f"station:{station_id}:transition:{observed_at.isoformat()}"

    @staticmethod
    def _normalize_transition_status(value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in _AVAILABLE_STATES:
            return "available"
        if normalized in _BUSY_STATES:
            return "busy"
        if normalized in _ONLINE_TRANSITION_STATES:
            return "unavailable"
        return normalized or "unavailable"

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _is_recent(self, end_time: datetime) -> bool:
        return self._as_utc(end_time) >= datetime.now(tz=UTC) - timedelta(
            minutes=self._settings.notification_recency_minutes
        )


class PushStationNotificationPoller:
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
            service = PushNotificationService(db=db, settings=self._settings)
            queue_service = QueueService(db=db)
            snapshots = list(self._occupancy_fetcher(db=db))
            created = 0
            free_station_ids_by_condo: dict[int, list[int]] = defaultdict(list)
            for snapshot in snapshots:
                previous_raw = self._previous_statuses.get(snapshot.station_id)
                previous_status = (
                    PushNotificationService._normalize_transition_status(previous_raw)
                    if previous_raw is not None
                    else None
                )
                current_status = PushNotificationService._normalize_transition_status(
                    snapshot.computed_status
                )
                self._previous_statuses[snapshot.station_id] = current_status
                if current_status == "available":
                    free_station_ids_by_condo[snapshot.condominium_id].append(snapshot.station_id)

                if previous_status != "busy" or current_status != "available":
                    continue

                station = db.get(ChargingStation, snapshot.station_id)
                if station is None:
                    continue
                transition_key = service._station_transition_key(
                    station_id=snapshot.station_id,
                    observed_at=snapshot.observed_at,
                )
                if queue_service.is_queue_enabled(
                    condominium_id=snapshot.condominium_id
                ) and queue_service.has_active_entries(condominium_id=snapshot.condominium_id):
                    offered_entry = queue_service.get_offered_entry_for_station(
                        condominium_id=snapshot.condominium_id,
                        station_id=snapshot.station_id,
                    )
                    entry = offered_entry or self._first_active_entry(
                        db=db,
                        condominium_id=snapshot.condominium_id,
                    )
                    if entry is not None:
                        resident = db.get(AppUser, entry.resident_app_user_id)
                        if resident is not None:
                            created += service.send_station_available(
                                condominium_id=snapshot.condominium_id,
                                resident=resident,
                                station=station,
                                observed_at=snapshot.observed_at,
                                transition_key=transition_key,
                            )

            now = datetime.now(tz=UTC)
            if self._queue_assignments_active(now=now):
                for condominium_id, station_ids in free_station_ids_by_condo.items():
                    if not station_ids or not queue_service.is_queue_enabled(
                        condominium_id=condominium_id
                    ):
                        continue
                    promoted_entries = queue_service.promote_waiting_entries(
                        condominium_id=condominium_id,
                        station_ids=station_ids,
                        reserved_at=now,
                        reservation_expires_at=now
                        + timedelta(
                            minutes=max(1, int(self._settings.queue_reservation_grace_minutes))
                        ),
                    )
                    for entry in promoted_entries:
                        resident = db.get(AppUser, entry.resident_app_user_id)
                        if resident is None:
                            continue
                        created += service.send_queue_next_in_line(
                            condominium_id=condominium_id,
                            resident=resident,
                            entry_id=entry.id,
                        )

            created += self._notify_active_first_positions(
                db=db,
                service=service,
                queue_service=queue_service,
            )
            return created

    def _notify_active_first_positions(
        self,
        *,
        db: Session,
        service: PushNotificationService,
        queue_service: QueueService,
    ) -> int:
        created = 0
        active_entries = db.scalars(
            select(ChargingQueueEntry)
            .where(
                ChargingQueueEntry.status.in_(
                    [QUEUE_ENTRY_STATUS_WAITING, QUEUE_ENTRY_STATUS_OFFERED]
                )
            )
            .order_by(
                ChargingQueueEntry.condominium_id.asc(),
                ChargingQueueEntry.joined_at.asc(),
                ChargingQueueEntry.id.asc(),
            )
        ).all()
        first_active_by_condo: dict[int, ChargingQueueEntry] = {}
        for entry in active_entries:
            if not queue_service.is_queue_enabled(condominium_id=entry.condominium_id):
                continue
            first_active_by_condo.setdefault(entry.condominium_id, entry)
        for entry in first_active_by_condo.values():
            resident = db.get(AppUser, entry.resident_app_user_id)
            if resident is None:
                continue
            created += service.send_queue_next_in_line(
                condominium_id=entry.condominium_id,
                resident=resident,
                entry_id=entry.id,
            )
        return created

    @staticmethod
    def _first_active_entry(*, db: Session, condominium_id: int) -> ChargingQueueEntry | None:
        return db.scalar(
            select(ChargingQueueEntry)
            .where(ChargingQueueEntry.condominium_id == condominium_id)
            .where(
                ChargingQueueEntry.status.in_(
                    [QUEUE_ENTRY_STATUS_WAITING, QUEUE_ENTRY_STATUS_OFFERED]
                )
            )
            .order_by(ChargingQueueEntry.joined_at.asc(), ChargingQueueEntry.id.asc())
            .limit(1)
        )

    def _queue_assignments_active(self, *, now: datetime) -> bool:
        local_hour = now.astimezone(_ROME_TZ).hour
        start_hour = int(self._settings.queue_assignment_start_hour)
        end_hour = int(self._settings.queue_assignment_end_hour)
        return start_hour <= local_hour < end_hour


class PushAgentStatusNotificationPoller:
    def __init__(
        self,
        *,
        db_factory: Callable[[], Session],
        settings: Settings,
    ) -> None:
        self._db_factory = db_factory
        self._settings = settings
        self._previous_online: dict[tuple[int, str], bool] = {}

    def poll_once(self, *, now: datetime | None = None) -> int:
        if not self._settings.notifications_enabled:
            return 0

        observed_at = now or datetime.now(tz=UTC)
        created = 0
        with self._db_factory() as db:
            service = PushNotificationService(db=db, settings=self._settings)
            states = db.scalars(select(AgentState).order_by(AgentState.id.asc())).all()
            for state in states:
                if state.last_heartbeat_at is None:
                    continue
                key = (state.condominium_id, state.agent_id)
                is_online = (
                    observed_at - PushNotificationService._as_utc(state.last_heartbeat_at)
                ).total_seconds() <= self._settings.telegram_agent_offline_threshold_seconds
                previous = self._previous_online.get(key)
                self._previous_online[key] = is_online
                if previous is None or previous == is_online or is_online:
                    continue
                for admin_user in service.list_subscribed_admins(
                    condominium_id=state.condominium_id
                ):
                    created += service.send_agent_offline(
                        condominium_id=state.condominium_id,
                        admin_user=admin_user,
                        agent_state=state,
                        detected_at=observed_at,
                    )
        return created
