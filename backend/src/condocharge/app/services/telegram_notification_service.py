from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from condocharge.app.services.queue_service import QueueService
from condocharge.app.services.resident_notification_service import (
    LiveStationAvailabilityFetcher,
    StationAvailabilitySnapshot,
)
from condocharge.app.services.telegram_bot_service import TelegramBotService, TelegramDeliveryError
from condocharge.core.config import Settings
from condocharge.models.charging import AgentState, ChargingSession, ChargingStation, RfidUser
from condocharge.models.queue import ChargingQueueEntry
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
NOTIFICATION_TYPE_STATION_BUSY = "station_busy"
NOTIFICATION_TYPE_STATION_BACK_ONLINE = "station_back_online"
NOTIFICATION_TYPE_CHARGING_COMPLETED = "charging_completed"
NOTIFICATION_TYPE_CHARGING_COMPLETED_REMINDER = "charging_completed_reminder"
NOTIFICATION_TYPE_CHARGING_COMPLETED_FINAL_REMINDER = "charging_completed_final_reminder"
NOTIFICATION_TYPE_QUEUE_TURN = "queue_turn"
NOTIFICATION_TYPE_QUEUE_RESERVATION_EXPIRED = "queue_reservation_expired"
NOTIFICATION_TYPE_QUEUE_RESERVATION_CANCELLED = "queue_reservation_cancelled"
NOTIFICATION_TYPE_AGENT_OFFLINE = "agent_offline"
NOTIFICATION_TYPE_AGENT_RECOVERED = "agent_recovered"
NOTIFICATION_TYPE_COMMAND_TEST = "command_test"

_AVAILABLE_STATES = {"available", "free"}
_BUSY_STATES = {"busy", "charging", "occupied"}
_UNAVAILABLE_STATES = {"unavailable", "offline", "faulted", "unknown", "unreachable", "degraded"}
_ONLINE_TRANSITION_STATES = {"checking", *sorted(_UNAVAILABLE_STATES)}
_ROME_TZ = ZoneInfo("Europe/Rome")


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
                f"Observed at: {self._format_local_dt(observed_at)}"
            ),
        )

    def send_station_busy(
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
            notification_type=NOTIFICATION_TYPE_STATION_BUSY,
        ):
            return None

        transition_key = transition_key or self._station_transition_key(
            station_id=station.id,
            transition_name="busy",
            observed_at=observed_at,
        )
        return self._deliver(
            condominium_id=condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_STATION_BUSY,
            dedupe_key=f"{transition_key}:resident:{resident.id}",
            text=self._build_station_busy_text(
                condominium_id=condominium_id,
                station=station,
                observed_at=observed_at,
            ),
        )

    def send_station_back_online(
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
            notification_type=NOTIFICATION_TYPE_STATION_BACK_ONLINE,
        ):
            return None

        transition_key = transition_key or self._station_transition_key(
            station_id=station.id,
            transition_name="back-online",
            observed_at=observed_at,
        )
        return self._deliver(
            condominium_id=condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_STATION_BACK_ONLINE,
            dedupe_key=f"{transition_key}:resident:{resident.id}",
            text=self._build_station_back_online_text(
                condominium_id=condominium_id,
                station=station,
                observed_at=observed_at,
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
            text=self._build_charging_completed_text(
                waiting_count=QueueService(db=self._db).active_count(condominium_id=session.condominium_id)
            ),
        )

    def send_charging_completed_reminder(
        self,
        *,
        session: ChargingSession,
        resident: AppUser,
        waiting_count: int,
        final: bool,
    ) -> ResidentNotificationHistory | None:
        if session.end_time is None or not self._is_recent(session.end_time):
            return None
        if not self._notifications_enabled(
            condominium_id=session.condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_CHARGING_COMPLETED,
        ):
            return None

        reminder_minutes = (
            self._settings.queue_completion_final_reminder_minutes
            if final
            else self._settings.queue_completion_reminder_minutes
        )
        notification_type = (
            NOTIFICATION_TYPE_CHARGING_COMPLETED_FINAL_REMINDER
            if final
            else NOTIFICATION_TYPE_CHARGING_COMPLETED_REMINDER
        )
        return self._deliver(
            condominium_id=session.condominium_id,
            resident=resident,
            notification_type=notification_type,
            dedupe_key=f"session:{session.id}:reminder:{int(reminder_minutes)}",
            text=self._build_charging_completed_reminder_text(
                waiting_count=waiting_count,
                reminder_minutes=int(reminder_minutes),
                final=final,
            ),
        )

    def send_queue_turn(
        self,
        *,
        condominium_id: int,
        resident: AppUser,
        entry_id: int,
    ) -> ResidentNotificationHistory | None:
        if not self._settings.notifications_enabled:
            return None
        return self._deliver(
            condominium_id=condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_QUEUE_TURN,
            dedupe_key=f"queue-entry:{entry_id}:turn",
            text=(
                "🟢 E il tuo turno.\n\n"
                "Hai 30 minuti per iniziare la ricarica."
            ),
        )

    def send_queue_reservation_expired(
        self,
        *,
        condominium_id: int,
        resident: AppUser,
        entry_id: int,
    ) -> ResidentNotificationHistory | None:
        if not self._settings.notifications_enabled:
            return None
        return self._deliver(
            condominium_id=condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_QUEUE_RESERVATION_EXPIRED,
            dedupe_key=f"queue-entry:{entry_id}:expired",
            text=(
                "⌛ Tempo scaduto.\n\n"
                "La prenotazione e stata annullata.\n\n"
                "Se desideri ricaricare, puoi rientrare in coda."
            ),
        )

    def send_queue_reservation_cancelled(
        self,
        *,
        condominium_id: int,
        resident: AppUser,
        entry_id: int,
    ) -> ResidentNotificationHistory | None:
        if not self._settings.notifications_enabled:
            return None
        return self._deliver(
            condominium_id=condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_QUEUE_RESERVATION_CANCELLED,
            dedupe_key=f"queue-entry:{entry_id}:cancelled",
            text=(
                "⌛ Prenotazione annullata.\n\n"
                "Il posto di ricarica non e piu disponibile.\n\n"
                "Se desideri ricaricare, puoi rientrare in coda."
            ),
        )

    def send_command_test(
        self,
        *,
        condominium_id: int,
        resident: AppUser,
        requested_at: datetime | None = None,
    ) -> ResidentNotificationHistory | None:
        now = self._as_utc(requested_at)
        return self._deliver(
            condominium_id=condominium_id,
            resident=resident,
            notification_type=NOTIFICATION_TYPE_COMMAND_TEST,
            dedupe_key=f"command-test:{resident.id}:{now.isoformat()}",
            text=(
                "CondoCharge test notification\n"
                f"Condominium: {self._condominium_name(condominium_id)}\n"
                f"Resident: {resident.username}\n"
                f"Requested at: {self._format_local_dt(now)}"
            ),
        )

    def send_admin_simulation(
        self,
        *,
        condominium_id: int,
        resident: AppUser,
        notification_type: str,
        station: ChargingStation | None = None,
        session: ChargingSession | None = None,
        agent_state: AgentState | None = None,
        observed_at: datetime | None = None,
    ) -> ResidentNotificationHistory | None:
        now = self._as_utc(observed_at)
        target_station = station or self._default_station(condominium_id=condominium_id)
        target_agent = agent_state or self._default_agent_state(condominium_id=condominium_id)
        target_session = session or self._default_session(condominium_id=condominium_id, resident=resident)
        text = self._simulation_text(
            condominium_id=condominium_id,
            notification_type=notification_type,
            station=target_station,
            session=target_session,
            agent_state=target_agent,
            observed_at=now,
            resident=resident,
        )
        if text is None:
            return None
        return self._deliver(
            condominium_id=condominium_id,
            resident=resident,
            notification_type=notification_type,
            dedupe_key=f"admin-sim:{notification_type}:{resident.id}:{now.isoformat()}",
            text=text,
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
            NOTIFICATION_TYPE_STATION_BUSY: condo.telegram_station_busy_enabled,
            NOTIFICATION_TYPE_STATION_BACK_ONLINE: condo.telegram_station_back_online_enabled,
            NOTIFICATION_TYPE_CHARGING_COMPLETED: condo.telegram_charging_completed_enabled,
            NOTIFICATION_TYPE_AGENT_OFFLINE: condo.telegram_agent_offline_enabled,
            NOTIFICATION_TYPE_AGENT_RECOVERED: condo.telegram_agent_recovered_enabled,
        }
        return bool(mapping.get(notification_type, 0))

    @staticmethod
    def _preference_clause(*, notification_type: str) -> ColumnElement[bool]:
        mapping = {
            NOTIFICATION_TYPE_STATION_AVAILABLE: ResidentNotificationPreferences.station_available == 1,
            NOTIFICATION_TYPE_STATION_BUSY: ResidentNotificationPreferences.station_busy == 1,
            NOTIFICATION_TYPE_STATION_BACK_ONLINE: ResidentNotificationPreferences.station_back_online == 1,
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

    def _build_station_busy_text(
        self,
        *,
        condominium_id: int,
        station: ChargingStation,
        observed_at: datetime,
    ) -> str:
        return (
            "🔴 Colonnina occupata\n\n"
            f"La colonnina {station.name or station.host} e stata occupata.\n\n"
            "Disponibilita attuale:\n"
            f"{self._station_summary(condominium_id=condominium_id)}\n\n"
            f"Osservato: {self._format_local_dt(observed_at)}"
        )

    def _build_station_back_online_text(
        self,
        *,
        condominium_id: int,
        station: ChargingStation,
        observed_at: datetime,
    ) -> str:
        return (
            "🟢 Colonnina tornata online\n\n"
            f"La colonnina {station.name or station.host} e nuovamente disponibile per l'utilizzo.\n\n"
            "Disponibilita attuale:\n"
            f"{self._station_summary(condominium_id=condominium_id)}\n\n"
            f"Osservato: {self._format_local_dt(observed_at)}"
        )

    @staticmethod
    def _build_charging_completed_text(*, waiting_count: int) -> str:
        return (
            "🔋 Ricarica completata\n\n"
            "Ti chiediamo di liberare il posto di ricarica.\n\n"
            f"Persone in attesa: {max(int(waiting_count), 0)}"
        )

    @staticmethod
    def _build_charging_completed_reminder_text(
        *,
        waiting_count: int,
        reminder_minutes: int,
        final: bool,
    ) -> str:
        title = "⏰ Ultimo promemoria" if final else "⏰ Promemoria"
        return (
            f"{title}\n\n"
            f"La tua ricarica e terminata da {int(reminder_minutes)} minuti.\n"
            "Ti chiediamo di liberare il posto di ricarica appena possibile.\n\n"
            f"Persone in attesa: {max(int(waiting_count), 0)}"
        )

    def _simulation_text(
        self,
        *,
        condominium_id: int,
        notification_type: str,
        station: ChargingStation | None,
        session: ChargingSession | None,
        agent_state: AgentState | None,
        observed_at: datetime,
        resident: AppUser,
    ) -> str | None:
        if notification_type == NOTIFICATION_TYPE_STATION_AVAILABLE and station is not None:
            return (
                "🧪 Test CondoCharge\n\n"
                f"CondoCharge: station available\n"
                f"Condominium: {self._condominium_name(condominium_id)}\n"
                f"Station: {station.name or station.host}\n"
                f"Observed at: {self._format_local_dt(observed_at)}"
            )
        if notification_type == NOTIFICATION_TYPE_STATION_BUSY and station is not None:
            return self._build_station_busy_text(
                condominium_id=condominium_id,
                station=station,
                observed_at=observed_at,
            )
        if notification_type == NOTIFICATION_TYPE_STATION_BACK_ONLINE and station is not None:
            return self._build_station_back_online_text(
                condominium_id=condominium_id,
                station=station,
                observed_at=observed_at,
            )
        if notification_type == NOTIFICATION_TYPE_CHARGING_COMPLETED and station is not None:
            energy_wh = int(session.energy_wh) if session is not None else 6200
            return (
                "🧪 Test CondoCharge\n\n"
                f"{self._build_charging_completed_text(waiting_count=0)}\n"
                f"Energia test: {self._format_kwh_wh(energy_wh)} kWh\n"
                f"Costo stimato test: €{self._format_eur(self._estimated_cost_eur(session, condominium_id=condominium_id, fallback_energy_wh=energy_wh))}"
            )
        if notification_type == NOTIFICATION_TYPE_AGENT_OFFLINE and agent_state is not None:
            return (
                "🧪 Test CondoCharge\n\n"
                "CondoCharge: agent offline\n"
                f"Condominium: {self._condominium_name(condominium_id)}\n"
                f"Agent: {agent_state.agent_id}\n"
                f"Last heartbeat: {self._format_dt(agent_state.last_heartbeat_at)}\n"
                f"Detected at: {self._format_local_dt(observed_at)}"
            )
        if notification_type == NOTIFICATION_TYPE_AGENT_RECOVERED and agent_state is not None:
            return (
                "🧪 Test CondoCharge\n\n"
                "CondoCharge: agent recovered\n"
                f"Condominium: {self._condominium_name(condominium_id)}\n"
                f"Agent: {agent_state.agent_id}\n"
                f"Last heartbeat: {self._format_dt(agent_state.last_heartbeat_at)}\n"
                f"Detected at: {self._format_local_dt(observed_at)}"
            )
        return None

    def _station_summary(self, *, condominium_id: int) -> str:
        stations = self._db.scalars(
            select(ChargingStation)
            .where(ChargingStation.condominium_id == condominium_id)
            .order_by(ChargingStation.id.asc())
        ).all()
        if not stations:
            return "- Nessuna colonnina"
        out: list[str] = []
        for station in stations:
            label = station.name or station.host
            out.append(f"* {label}: {self._station_status_label(station.status)}")
        return "\n".join(out)

    @staticmethod
    def _station_status_label(status: str | None) -> str:
        normalized = ResidentTelegramNotificationService._normalize_transition_status(status)
        if normalized == "available":
            return "Libera"
        if normalized == "busy":
            return "Occupata"
        return "Non disponibile"

    def _default_station(self, *, condominium_id: int) -> ChargingStation | None:
        return self._db.scalar(
            select(ChargingStation)
            .where(ChargingStation.condominium_id == condominium_id)
            .order_by(ChargingStation.id.asc())
            .limit(1)
        )

    def _default_agent_state(self, *, condominium_id: int) -> AgentState | None:
        return self._db.scalar(
            select(AgentState)
            .where(AgentState.condominium_id == condominium_id)
            .order_by(AgentState.id.asc())
            .limit(1)
        )

    def _default_session(self, *, condominium_id: int, resident: AppUser) -> ChargingSession | None:
        return self._db.scalar(
            select(ChargingSession)
            .join(RfidUser, RfidUser.id == ChargingSession.rfid_user_id)
            .where(ChargingSession.condominium_id == condominium_id)
            .where(RfidUser.app_user_id == resident.id)
            .order_by(ChargingSession.end_time.desc(), ChargingSession.id.desc())
            .limit(1)
        )

    @staticmethod
    def _station_transition_key(*, station_id: int, observed_at: datetime, transition_name: str = "available") -> str:
        return f"station:{station_id}:transition:{transition_name}:{observed_at.isoformat()}"

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
        return self._format_local_dt(value)

    def _format_local_dt(self, value: datetime | None) -> str:
        return self._as_utc(value).astimezone(_ROME_TZ).strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _format_kwh_wh(energy_wh: int | None) -> str:
        return ResidentTelegramNotificationService._format_kwh((int(energy_wh or 0)) / 1000.0)

    @staticmethod
    def _format_kwh(energy_kwh: float) -> str:
        return f"{energy_kwh:.3f}".rstrip("0").rstrip(".") or "0"

    @staticmethod
    def _format_eur(amount: float) -> str:
        return f"{amount:.2f}"

    def _estimated_cost_eur(
        self,
        session: ChargingSession | None,
        *,
        condominium_id: int | None = None,
        fallback_energy_wh: int | None = None,
    ) -> float:
        target_condominium_id = condominium_id or (session.condominium_id if session is not None else None)
        condo = self._db.get(Condominium, target_condominium_id) if target_condominium_id is not None else None
        price = float(condo.energy_price_eur_per_kwh) if condo is not None else 0.0
        energy_wh = int(session.energy_wh) if session is not None else int(fallback_energy_wh or 0)
        return round((energy_wh / 1000.0) * price, 2)


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
            queue_service = QueueService(db=db)
            snapshots = list(self._occupancy_fetcher(db=db))
            created = 0
            free_station_ids_by_condo: dict[int, list[int]] = defaultdict(list)
            busy_transition_station_ids_by_condo: dict[int, list[int]] = defaultdict(list)
            status_by_station_id: dict[int, str] = {}

            for snapshot in snapshots:
                previous_raw = self._previous_statuses.get(snapshot.station_id)
                previous_status = (
                    ResidentTelegramNotificationService._normalize_transition_status(previous_raw)
                    if previous_raw is not None
                    else None
                )
                current_status = ResidentTelegramNotificationService._normalize_transition_status(snapshot.computed_status)
                self._previous_statuses[snapshot.station_id] = current_status
                status_by_station_id[snapshot.station_id] = current_status
                station = db.get(ChargingStation, snapshot.station_id)
                if station is None:
                    continue
                if current_status == "available":
                    free_station_ids_by_condo[snapshot.condominium_id].append(snapshot.station_id)
                if previous_status == "available" and current_status == "busy":
                    busy_transition_station_ids_by_condo[snapshot.condominium_id].append(snapshot.station_id)

                event_name: str | None = None
                if previous_status == "busy" and current_status == "available":
                    event_name = NOTIFICATION_TYPE_STATION_AVAILABLE
                elif previous_status == "available" and current_status == "busy":
                    event_name = NOTIFICATION_TYPE_STATION_BUSY
                elif previous_status == "unavailable" and current_status == "available":
                    event_name = NOTIFICATION_TYPE_STATION_BACK_ONLINE

                if event_name is None:
                    continue
                if (
                    event_name == NOTIFICATION_TYPE_STATION_AVAILABLE
                    and queue_service.is_queue_enabled(condominium_id=snapshot.condominium_id)
                    and queue_service.has_active_entries(condominium_id=snapshot.condominium_id)
                ):
                    continue

                transition_key = service._station_transition_key(
                    station_id=snapshot.station_id,
                    transition_name=event_name,
                    observed_at=snapshot.observed_at,
                )
                for resident in service.list_linked_residents(
                    condominium_id=snapshot.condominium_id,
                    notification_type=event_name,
                ):
                    row = None
                    if event_name == NOTIFICATION_TYPE_STATION_AVAILABLE:
                        row = service.send_station_available(
                            condominium_id=snapshot.condominium_id,
                            resident=resident,
                            station=station,
                            observed_at=snapshot.observed_at,
                            transition_key=transition_key,
                        )
                    elif event_name == NOTIFICATION_TYPE_STATION_BUSY:
                        row = service.send_station_busy(
                            condominium_id=snapshot.condominium_id,
                            resident=resident,
                            station=station,
                            observed_at=snapshot.observed_at,
                            transition_key=transition_key,
                        )
                    elif event_name == NOTIFICATION_TYPE_STATION_BACK_ONLINE:
                        row = service.send_station_back_online(
                            condominium_id=snapshot.condominium_id,
                            resident=resident,
                            station=station,
                            observed_at=snapshot.observed_at,
                            transition_key=transition_key,
                        )
                    if row is not None:
                        created += 1

            observed_at = datetime.now(tz=UTC)
            for condominium_id, station_ids in busy_transition_station_ids_by_condo.items():
                created += self._resolve_busy_station_reservations(
                    db=db,
                    service=service,
                    queue_service=queue_service,
                    condominium_id=condominium_id,
                    station_ids=station_ids,
                    observed_at=observed_at,
                )

            expired_entries = queue_service.expire_overdue_reservations(now=observed_at)
            for entry in expired_entries:
                expired_resident = db.get(AppUser, entry.resident_app_user_id)
                if expired_resident is None:
                    continue
                row = service.send_queue_reservation_expired(
                    condominium_id=entry.condominium_id,
                    resident=expired_resident,
                    entry_id=entry.id,
                )
                if row is not None:
                    created += 1

            if self._queue_assignments_active(now=observed_at):
                created += self._send_due_completion_reminders(
                    db=db,
                    service=service,
                    queue_service=queue_service,
                    now=observed_at,
                    status_by_station_id=status_by_station_id,
                )
                created += self._promote_waiting_residents(
                    db=db,
                    service=service,
                    queue_service=queue_service,
                    now=observed_at,
                    free_station_ids_by_condo=free_station_ids_by_condo,
                )

            return created

    def _promote_waiting_residents(
        self,
        *,
        db: Session,
        service: ResidentTelegramNotificationService,
        queue_service: QueueService,
        now: datetime,
        free_station_ids_by_condo: dict[int, list[int]],
    ) -> int:
        created = 0
        grace_minutes = max(1, int(self._settings.queue_reservation_grace_minutes))
        expires_at = now + timedelta(minutes=grace_minutes)
        for condominium_id, station_ids in free_station_ids_by_condo.items():
            if not station_ids or not queue_service.is_queue_enabled(condominium_id=condominium_id):
                continue
            promoted_entries = queue_service.promote_waiting_entries(
                condominium_id=condominium_id,
                station_ids=station_ids,
                reserved_at=now,
                reservation_expires_at=expires_at,
            )
            for entry in promoted_entries:
                resident = db.get(AppUser, entry.resident_app_user_id)
                if resident is None:
                    continue
                row = service.send_queue_turn(
                    condominium_id=condominium_id,
                    resident=resident,
                    entry_id=entry.id,
                )
                if row is not None:
                    created += 1
        return created

    def _resolve_busy_station_reservations(
        self,
        *,
        db: Session,
        service: ResidentTelegramNotificationService,
        queue_service: QueueService,
        condominium_id: int,
        station_ids: list[int],
        observed_at: datetime,
    ) -> int:
        created = 0
        for station_id in station_ids:
            entry = queue_service.get_offered_entry_for_station(
                condominium_id=condominium_id,
                station_id=station_id,
            )
            if entry is None:
                continue

            expires_at = ResidentTelegramNotificationService._as_utc(entry.reservation_expires_at)
            if expires_at is None or observed_at > expires_at:
                queue_service.cancel_offered_reservation(
                    entry=entry,
                    cancelled_at=observed_at,
                    reason="reservation_expired_station_busy",
                )
                resident = db.get(AppUser, entry.resident_app_user_id)
                if resident is None:
                    continue
                row = service.send_queue_reservation_expired(
                    condominium_id=condominium_id,
                    resident=resident,
                    entry_id=entry.id,
                )
                if row is not None:
                    created += 1
                continue

            matched_resident_app_user_id = self._matching_started_resident_app_user_id(
                db=db,
                entry=entry,
                observed_at=observed_at,
            )
            if matched_resident_app_user_id == entry.resident_app_user_id:
                queue_service.mark_started_reservation(entry=entry, started_at=observed_at)
                continue

            reason = (
                "reservation_cancelled_station_taken_by_other_resident"
                if matched_resident_app_user_id is not None
                else "reservation_cancelled_station_busy_without_resident_mapping"
            )
            queue_service.cancel_offered_reservation(
                entry=entry,
                cancelled_at=observed_at,
                reason=reason,
            )
            resident = db.get(AppUser, entry.resident_app_user_id)
            if resident is None:
                continue
            row = service.send_queue_reservation_cancelled(
                condominium_id=condominium_id,
                resident=resident,
                entry_id=entry.id,
            )
            if row is not None:
                created += 1
        return created

    def _matching_started_resident_app_user_id(
        self,
        *,
        db: Session,
        entry: ChargingQueueEntry,
        observed_at: datetime,
    ) -> int | None:
        reserved_at = ResidentTelegramNotificationService._as_utc(entry.reserved_at)
        expires_at = ResidentTelegramNotificationService._as_utc(entry.reservation_expires_at)
        if reserved_at is None or expires_at is None or entry.reserved_station_id is None:
            return None

        latest_session = db.scalar(
            select(ChargingSession)
            .where(ChargingSession.condominium_id == entry.condominium_id)
            .where(ChargingSession.station_id == entry.reserved_station_id)
            .where(ChargingSession.start_time >= reserved_at)
            .where(ChargingSession.start_time <= min(observed_at, expires_at))
            .order_by(ChargingSession.start_time.desc(), ChargingSession.id.desc())
            .limit(1)
        )
        if latest_session is None or latest_session.rfid_user_id is None:
            return None
        rfid_user = db.get(RfidUser, latest_session.rfid_user_id)
        if rfid_user is None:
            return None
        return rfid_user.app_user_id

    def _send_due_completion_reminders(
        self,
        *,
        db: Session,
        service: ResidentTelegramNotificationService,
        queue_service: QueueService,
        now: datetime,
        status_by_station_id: dict[int, str],
    ) -> int:
        created = 0
        reminder_minutes = max(1, int(self._settings.queue_completion_reminder_minutes))
        final_minutes = max(reminder_minutes, int(self._settings.queue_completion_final_reminder_minutes))
        window_start = now - timedelta(minutes=final_minutes + 5)
        sessions = (
            db.scalars(
                select(ChargingSession)
                .join(RfidUser, RfidUser.id == ChargingSession.rfid_user_id)
                .where(RfidUser.app_user_id.is_not(None))
                .where(ChargingSession.end_time >= window_start)
                .order_by(ChargingSession.end_time.desc(), ChargingSession.id.desc())
            )
            .all()
        )
        for session in sessions:
            if session.end_time is None:
                continue
            if status_by_station_id.get(session.station_id) != "busy":
                continue
            rfid_user = db.get(RfidUser, session.rfid_user_id) if session.rfid_user_id is not None else None
            if rfid_user is None or rfid_user.app_user_id is None:
                continue
            resident = db.get(AppUser, rfid_user.app_user_id)
            if resident is None:
                continue
            elapsed_minutes = (now - ResidentTelegramNotificationService._as_utc(session.end_time)).total_seconds() / 60.0
            waiting_count = queue_service.active_count(condominium_id=session.condominium_id)
            if elapsed_minutes >= final_minutes:
                row = service.send_charging_completed_reminder(
                    session=session,
                    resident=resident,
                    waiting_count=waiting_count,
                    final=True,
                )
                if row is not None:
                    created += 1
                continue
            if elapsed_minutes >= reminder_minutes:
                row = service.send_charging_completed_reminder(
                    session=session,
                    resident=resident,
                    waiting_count=waiting_count,
                    final=False,
                )
                if row is not None:
                    created += 1
        return created

    def _queue_assignments_active(self, *, now: datetime) -> bool:
        local_hour = now.astimezone(_ROME_TZ).hour
        start_hour = int(self._settings.queue_assignment_start_hour)
        end_hour = int(self._settings.queue_assignment_end_hour)
        return start_hour <= local_hour < end_hour


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
