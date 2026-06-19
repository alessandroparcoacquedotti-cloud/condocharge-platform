from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from condocharge.app.services.resident_notification_service import (
    LiveStationAvailabilityFetcher,
    NON_AVAILABLE_STATION_STATES,
    StationAvailabilitySnapshot,
)
from condocharge.app.services.telegram_bot_service import TelegramBotService, TelegramDeliveryError
from condocharge.core.config import Settings
from condocharge.models.charging import AgentState, ChargingSession, ChargingStation
from condocharge.models.tenancy import (
    AppUser,
    AppUserRole,
    Condominium,
    ResidentNotificationHistory,
    ResidentNotificationPreferences,
)

CHANNEL_TELEGRAM = "telegram"
STATUS_SENT = "sent"
STATUS_PREVIEW = "preview"
STATUS_FAILED = "failed"

NOTIFICATION_TYPE_STATION_AVAILABLE = "station_available"
NOTIFICATION_TYPE_CHARGING_COMPLETED = "charging_completed"
NOTIFICATION_TYPE_AGENT_OFFLINE = "agent_offline"
NOTIFICATION_TYPE_AGENT_RECOVERED = "agent_recovered"


class ResidentTelegramNotificationService:
    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        bot_service: TelegramBotService | None = None,
    ) -> None:
        self._db = db
        self._settings = settings
        self._bot_service = bot_service or TelegramBotService(settings=settings)

    def send_station_available(
        self,
        *,
        condominium_id: int,
        resident: AppUser,
        station: ChargingStation,
        observed_at: datetime,
        transition_key: str | None = None,
    ) -> ResidentNotificationHistory | None:
        if not self._notifications_enabled(
            condominium_id=condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_STATION_AVAILABLE,
        ):
            return None

        chat_id = self._chat_id(resident)
        if chat_id is None:
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
        if self._resident_station_available_cooldown_active(resident_id=resident.id, now=observed_at):
            return None

        return self._deliver(
            condominium_id=condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_STATION_AVAILABLE,
            dedupe_key=dedupe_key,
            text=(
                f"CondoCharge: station available\n"
                f"Condominium: {self._condominium_name(condominium_id)}\n"
                f"Station: {station.name or station.host}\n"
                f"Observed at: {self._as_utc(observed_at).isoformat()}"
            ),
        )

    def send_charging_completed(
        self,
        *,
        session: ChargingSession,
        resident: AppUser,
        station: ChargingStation,
    ) -> ResidentNotificationHistory | None:
        if session.end_time is None or not self._is_recent(session.end_time):
            return None
        if not self._notifications_enabled(
            condominium_id=session.condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_CHARGING_COMPLETED,
        ):
            return None

        return self._deliver(
            condominium_id=session.condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_CHARGING_COMPLETED,
            dedupe_key=f"session:{session.id}",
            text=(
                f"CondoCharge: charging session completed\n"
                f"Condominium: {self._condominium_name(session.condominium_id)}\n"
                f"Station: {station.name or station.host}\n"
                f"Ended at: {self._as_utc(session.end_time).isoformat()}\n"
                f"Energy: {int(session.energy_wh)} Wh\n"
                f"Duration: {int(session.total_minutes)} minutes"
            ),
        )

    def send_agent_offline(
        self,
        *,
        condominium_id: int,
        resident: AppUser,
        agent_state: AgentState,
        detected_at: datetime,
    ) -> ResidentNotificationHistory | None:
        if not self._notifications_enabled(
            condominium_id=condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_AGENT_OFFLINE,
        ):
            return None

        return self._deliver(
            condominium_id=condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_AGENT_OFFLINE,
            dedupe_key=f"agent:{agent_state.agent_id}:offline:{self._as_utc(agent_state.last_heartbeat_at).isoformat()}",
            text=(
                f"CondoCharge: agent offline\n"
                f"Condominium: {self._condominium_name(condominium_id)}\n"
                f"Agent: {agent_state.agent_id}\n"
                f"Last heartbeat: {self._format_dt(agent_state.last_heartbeat_at)}\n"
                f"Detected at: {self._as_utc(detected_at).isoformat()}"
            ),
        )

    def send_agent_recovered(
        self,
        *,
        condominium_id: int,
        resident: AppUser,
        agent_state: AgentState,
        detected_at: datetime,
    ) -> ResidentNotificationHistory | None:
        if not self._notifications_enabled(
            condominium_id=condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_AGENT_RECOVERED,
        ):
            return None

        return self._deliver(
            condominium_id=condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_AGENT_RECOVERED,
            dedupe_key=f"agent:{agent_state.agent_id}:recovered:{self._as_utc(detected_at).isoformat()}",
            text=(
                f"CondoCharge: agent recovered\n"
                f"Condominium: {self._condominium_name(condominium_id)}\n"
                f"Agent: {agent_state.agent_id}\n"
                f"Last heartbeat: {self._format_dt(agent_state.last_heartbeat_at)}\n"
                f"Detected at: {self._as_utc(detected_at).isoformat()}"
            ),
        )

    def _deliver(
        self,
        *,
        condominium_id: int,
        resident: AppUser,
        notification_type: str,
        dedupe_key: str,
        text: str,
    ) -> ResidentNotificationHistory | None:
        chat_id = self._chat_id(resident)
        if chat_id is None:
            return None

        existing = self._existing_notification(
            condominium_id=condominium_id,
            notification_type=notification_type,
            dedupe_key=dedupe_key,
        )
        if existing is not None:
            return None

        if not self._bot_service.enabled:
            return self._create_history(
                condominium_id=condominium_id,
                resident_app_user_id=resident.id,
                recipient=chat_id,
                notification_type=notification_type,
                dedupe_key=dedupe_key,
                status=STATUS_PREVIEW,
            )

        try:
            result = self._bot_service.send_message(chat_id=chat_id, text=text)
        except TelegramDeliveryError as exc:
            return self._create_history(
                condominium_id=condominium_id,
                resident_app_user_id=resident.id,
                recipient=chat_id,
                notification_type=notification_type,
                dedupe_key=dedupe_key,
                status=STATUS_FAILED,
                error_message=str(exc)[:1000],
            )

        return self._create_history(
            condominium_id=condominium_id,
            resident_app_user_id=resident.id,
            recipient=chat_id,
            notification_type=notification_type,
            dedupe_key=dedupe_key,
            status=STATUS_SENT,
            sent_at=datetime.now(tz=UTC),
            provider_message_id=result.message_id,
        )

    def _create_history(
        self,
        *,
        condominium_id: int,
        resident_app_user_id: int,
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
            resident_app_user_id=resident_app_user_id,
            channel=CHANNEL_TELEGRAM,
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
            .where(ResidentNotificationHistory.channel == CHANNEL_TELEGRAM)
            .where(ResidentNotificationHistory.notification_type == notification_type)
            .where(ResidentNotificationHistory.dedupe_key == dedupe_key)
            .limit(1)
        )

    def list_linked_residents(self, *, condominium_id: int, notification_type: str) -> list[AppUser]:
        preference_clause = self._preference_clause(notification_type=notification_type)
        return list(
            self._db.scalars(
                select(AppUser)
                .outerjoin(ResidentNotificationPreferences, ResidentNotificationPreferences.app_user_id == AppUser.id)
                .where(AppUser.condominium_id == condominium_id)
                .where(AppUser.role == AppUserRole.RESIDENT.value)
                .where(AppUser.is_active == 1)
                .where(AppUser.telegram_chat_id.is_not(None))
                .where(AppUser.telegram_chat_id != "")
                .where(or_(ResidentNotificationPreferences.id.is_(None), preference_clause))
                .order_by(AppUser.id.asc())
            ).all()
        )

    def _notifications_enabled(self, *, condominium_id: int, resident: AppUser, notification_type: str) -> bool:
        if not self._settings.notifications_enabled:
            return False
        if self._chat_id(resident) is None:
            return False
        if not self._admin_toggle_enabled(condominium_id=condominium_id, notification_type=notification_type):
            return False
        return self._resident_pref_enabled(resident_id=resident.id, notification_type=notification_type)

    def _resident_pref_enabled(self, *, resident_id: int, notification_type: str) -> bool:
        preference_clause = self._preference_clause(notification_type=notification_type)
        return (
            self._db.scalar(
                select(AppUser.id)
                .outerjoin(ResidentNotificationPreferences, ResidentNotificationPreferences.app_user_id == AppUser.id)
                .where(AppUser.id == resident_id)
                .where(AppUser.role == AppUserRole.RESIDENT.value)
                .where(AppUser.is_active == 1)
                .where(AppUser.telegram_chat_id.is_not(None))
                .where(AppUser.telegram_chat_id != "")
                .where(or_(ResidentNotificationPreferences.id.is_(None), preference_clause))
                .limit(1)
            )
            is not None
        )

    def _admin_toggle_enabled(self, *, condominium_id: int, notification_type: str) -> bool:
        condo = self._db.get(Condominium, condominium_id)
        if condo is None:
            return False
        mapping = {
            NOTIFICATION_TYPE_STATION_AVAILABLE: condo.telegram_station_available_enabled,
            NOTIFICATION_TYPE_CHARGING_COMPLETED: condo.telegram_charging_completed_enabled,
            NOTIFICATION_TYPE_AGENT_OFFLINE: condo.telegram_agent_offline_enabled,
            NOTIFICATION_TYPE_AGENT_RECOVERED: condo.telegram_agent_recovered_enabled,
        }
        return bool(mapping.get(notification_type, 0))

    @staticmethod
    def _preference_clause(*, notification_type: str):
        mapping = {
            NOTIFICATION_TYPE_STATION_AVAILABLE: ResidentNotificationPreferences.station_available == 1,
            NOTIFICATION_TYPE_CHARGING_COMPLETED: ResidentNotificationPreferences.charging_completed == 1,
            NOTIFICATION_TYPE_AGENT_OFFLINE: ResidentNotificationPreferences.agent_offline == 1,
            NOTIFICATION_TYPE_AGENT_RECOVERED: ResidentNotificationPreferences.agent_recovered == 1,
        }
        return mapping[notification_type]

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
                .where(ResidentNotificationHistory.channel == CHANNEL_TELEGRAM)
                .where(ResidentNotificationHistory.notification_type == NOTIFICATION_TYPE_STATION_AVAILABLE)
                .where(ResidentNotificationHistory.created_at >= cutoff)
                .where(ResidentNotificationHistory.dedupe_key.like(f"station:{station_id}:transition:%"))
                .where(not_(ResidentNotificationHistory.dedupe_key.like(f"{transition_key}:resident:%")))
                .limit(1)
            )
            is not None
        )

    def _resident_station_available_cooldown_active(self, *, resident_id: int, now: datetime) -> bool:
        cutoff = now - timedelta(minutes=self._settings.notification_resident_cooldown_minutes)
        return (
            self._db.scalar(
                select(ResidentNotificationHistory.id)
                .where(ResidentNotificationHistory.resident_app_user_id == resident_id)
                .where(ResidentNotificationHistory.channel == CHANNEL_TELEGRAM)
                .where(ResidentNotificationHistory.notification_type == NOTIFICATION_TYPE_STATION_AVAILABLE)
                .where(ResidentNotificationHistory.created_at >= cutoff)
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
        return condo.name if condo is not None else "CondoCharge"

    @staticmethod
    def _station_transition_key(*, station_id: int, observed_at: datetime) -> str:
        return f"station:{station_id}:transition:{observed_at.isoformat()}"

    @staticmethod
    def _chat_id(resident: AppUser) -> str | None:
        value = (resident.telegram_chat_id or "").strip()
        return value or None

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(tz=UTC)
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _format_dt(self, value: datetime | None) -> str:
        if value is None:
            return "-"
        return self._as_utc(value).isoformat()


class TelegramStationAvailabilityNotificationPoller:
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
            service = ResidentTelegramNotificationService(db=db, settings=self._settings)
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
                for resident in service.list_linked_residents(
                    condominium_id=snapshot.condominium_id,
                    notification_type=NOTIFICATION_TYPE_STATION_AVAILABLE,
                ):
                    if (
                        service.send_station_available(
                            condominium_id=snapshot.condominium_id,
                            resident=resident,
                            station=station,
                            observed_at=snapshot.observed_at,
                            transition_key=transition_key,
                        )
                        is not None
                    ):
                        created += 1

            return created


class TelegramAgentStatusNotificationPoller:
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
            service = ResidentTelegramNotificationService(db=db, settings=self._settings)
            states = db.scalars(select(AgentState).order_by(AgentState.id.asc())).all()
            for state in states:
                if state.last_heartbeat_at is None:
                    continue
                key = (state.condominium_id, state.agent_id)
                is_online = (
                    observed_at - ResidentTelegramNotificationService._as_utc(state.last_heartbeat_at)
                ).total_seconds() <= self._settings.telegram_agent_offline_threshold_seconds
                previous = self._previous_online.get(key)
                self._previous_online[key] = is_online
                if previous is None or previous == is_online:
                    continue

                notification_type = (
                    NOTIFICATION_TYPE_AGENT_RECOVERED if is_online else NOTIFICATION_TYPE_AGENT_OFFLINE
                )
                residents = service.list_linked_residents(
                    condominium_id=state.condominium_id,
                    notification_type=notification_type,
                )
                for resident in residents:
                    row = (
                        service.send_agent_recovered(
                            condominium_id=state.condominium_id,
                            resident=resident,
                            agent_state=state,
                            detected_at=observed_at,
                        )
                        if is_online
                        else service.send_agent_offline(
                            condominium_id=state.condominium_id,
                            resident=resident,
                            agent_state=state,
                            detected_at=observed_at,
                        )
                    )
                    if row is not None:
                        created += 1
        return created
