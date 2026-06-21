from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.api.deps import get_db_session
from condocharge.app.services.resident_notification_service import StationAvailabilitySnapshot
from condocharge.app.services.resident_telegram_link_service import ResidentTelegramLinkService
from condocharge.app.services.telegram_bot_service import TelegramBotService, TelegramDeliveryError, TelegramSendResult
from condocharge.app.services.telegram_notification_service import (
    NOTIFICATION_TYPE_AGENT_OFFLINE,
    NOTIFICATION_TYPE_AGENT_RECOVERED,
    NOTIFICATION_TYPE_CHARGING_COMPLETED,
    NOTIFICATION_TYPE_CHARGING_COMPLETED_FINAL_REMINDER,
    NOTIFICATION_TYPE_CHARGING_COMPLETED_REMINDER,
    NOTIFICATION_TYPE_QUEUE_RESERVATION_CANCELLED,
    NOTIFICATION_TYPE_COMMAND_TEST,
    NOTIFICATION_TYPE_QUEUE_RESERVATION_EXPIRED,
    NOTIFICATION_TYPE_QUEUE_TURN,
    NOTIFICATION_TYPE_STATION_AVAILABLE,
    NOTIFICATION_TYPE_STATION_BACK_ONLINE,
    NOTIFICATION_TYPE_STATION_BUSY,
    ResidentTelegramNotificationService,
    TelegramAgentStatusNotificationPoller,
    TelegramStationAvailabilityNotificationPoller,
)
from condocharge.core.config import Settings, get_settings
from condocharge.core.security import hash_password
from condocharge.db.base import Base
from condocharge.main import create_app
from condocharge.models.charging import AgentState, ChargingSession, ChargingStation, RfidUser
from condocharge.models.queue import (
    QUEUE_ENTRY_STATUS_LEFT,
    QUEUE_ENTRY_STATUS_OFFERED,
    QUEUE_ENTRY_STATUS_WAITING,
    ChargingQueueEntry,
    ChargingQueueSettings,
)
from condocharge.models.tenancy import (
    AppUser,
    AppUserRole,
    Condominium,
    ResidentNotificationHistory,
    ResidentNotificationPreferences,
    ResidentTelegramLinkToken,
)
from condocharge.schemas.api import StationOccupancyResponse


class FakeTelegramApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, method: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append((method, payload))
        if method == "getMe":
            return {"ok": True, "result": {"username": "CondoChargeBot"}}
        return {"ok": True, "result": {"message_id": len(self.calls)}}


class SequenceOccupancyFetcher:
    def __init__(self, snapshots_by_call: list[Sequence[StationAvailabilitySnapshot]]) -> None:
        self._snapshots_by_call = snapshots_by_call
        self._index = 0

    def __call__(self, *, db: Session) -> Sequence[StationAvailabilitySnapshot]:
        del db
        result = self._snapshots_by_call[min(self._index, len(self._snapshots_by_call) - 1)]
        self._index += 1
        return result


def _build_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)
    return testing_session_local


def _build_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "notifications_enabled": True,
        "telegram_bot_token": "test-telegram-token",
        "telegram_bot_username": "CondoChargeBot",
        "notification_recency_minutes": 30,
        "notification_station_cooldown_minutes": 15,
        "notification_resident_cooldown_minutes": 5,
    }
    values.update(overrides)
    return Settings(**values)


def _seed_condo(db: Session) -> Condominium:
    condo = Condominium(name="Test Condo")
    db.add(condo)
    db.commit()
    db.refresh(condo)
    return condo


def _seed_resident(
    db: Session,
    *,
    condo: Condominium,
    username: str = "resident",
    linked_telegram: bool = True,
) -> AppUser:
    resident = AppUser(
        condominium_id=condo.id,
        username=username,
        email=f"{username}@example.com",
        telegram_chat_id=("123456" if username == "resident" else f"chat-{username}") if linked_telegram else None,
        telegram_username=username,
        telegram_linked_at=datetime.now(tz=UTC) if linked_telegram else None,
        password_hash="hash",
        role=AppUserRole.RESIDENT.value,
        is_active=1,
    )
    db.add(resident)
    db.flush()
    db.add(
        ResidentNotificationPreferences(
            condominium_id=condo.id,
            app_user_id=resident.id,
            charging_completed=1,
            station_available=1,
            station_busy=1,
            station_back_online=0,
            agent_offline=1,
            agent_recovered=1,
        )
    )
    db.commit()
    db.refresh(resident)
    return resident


def _seed_station(db: Session, *, condo: Condominium, host: str = "192.168.1.200") -> ChargingStation:
    station = ChargingStation(condominium_id=condo.id, host=host, vendor="legrand_greenup", name="Garage A")
    db.add(station)
    db.commit()
    db.refresh(station)
    return station


def _seed_session(
    db: Session,
    *,
    condo: Condominium,
    resident: AppUser,
    station: ChargingStation,
    start_time: datetime | None = None,
    end_time: datetime,
    mapped_app_user_id: int | None | object = ...,
) -> ChargingSession:
    rfid = RfidUser(
        condominium_id=condo.id,
        app_user_id=resident.id if mapped_app_user_id is ... else mapped_app_user_id,
        rfid_id=f"RFID-{resident.id}",
        name=resident.username,
    )
    db.add(rfid)
    db.flush()
    row = ChargingSession(
        condominium_id=condo.id,
        source_key=f"session-{resident.id}-{int(end_time.timestamp())}",
        station_id=station.id,
        rfid_user_id=rfid.id,
        start_time=start_time or (end_time - timedelta(hours=1)),
        end_time=end_time,
        energy_wh=6200,
        total_minutes=60,
        charging_minutes=55,
        idle_minutes=5,
        plug_type="Type2",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _enable_queue(db: Session, *, condo: Condominium) -> None:
    db.add(ChargingQueueSettings(condominium_id=condo.id, queue_enabled=1))
    db.commit()


def _seed_queue_entry(
    db: Session,
    *,
    condo: Condominium,
    resident: AppUser,
    station: ChargingStation | None = None,
    status: str = QUEUE_ENTRY_STATUS_WAITING,
    joined_at: datetime | None = None,
    reserved_at: datetime | None = None,
    reservation_expires_at: datetime | None = None,
) -> ChargingQueueEntry:
    row = ChargingQueueEntry(
        condominium_id=condo.id,
        resident_app_user_id=resident.id,
        reserved_station_id=station.id if station is not None else None,
        status=status,
        joined_at=joined_at or datetime.now(tz=UTC),
        reserved_at=reserved_at,
        reservation_expires_at=reservation_expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _set_station_busy_enabled(db: Session, *, resident: AppUser, enabled: bool) -> None:
    row = db.scalar(
        select(ResidentNotificationPreferences)
        .where(ResidentNotificationPreferences.app_user_id == resident.id)
        .limit(1)
    )
    assert row is not None
    row.station_busy = 1 if enabled else 0
    db.commit()


def test_resident_telegram_link_service_stores_chat_id() -> None:
    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo, linked_telegram=False)
        settings = _build_settings()
        service = ResidentTelegramLinkService(
            db=db,
            settings=settings,
            deep_link_builder=lambda token: f"https://t.me/CondoChargeBot?start={token}",
        )

        issue = service.issue_link(resident=resident)
        linked = service.link_chat(token=issue.token, chat_id="998877", telegram_username="resident_bot")

        token_row = db.scalar(select(ResidentTelegramLinkToken))
        assert linked.telegram_chat_id == "998877"
        assert linked.telegram_username == "resident_bot"
        assert linked.telegram_linked_at is not None
        assert token_row is not None
        assert token_row.used_at is not None


def test_resident_telegram_deep_link_round_trips_exact_token() -> None:
    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo, linked_telegram=False)
        settings = _build_settings()
        service = ResidentTelegramLinkService(
            db=db,
            settings=settings,
            deep_link_builder=lambda token: f"https://t.me/CondoChargeBot?start={token}",
        )

        issue = service.issue_link(resident=resident)
        parsed = parse_qs(urlparse(issue.deep_link_url or "").query)

        assert parsed["start"] == [issue.token]


def test_telegram_service_dedupes_charging_completed() -> None:
    session_factory = _build_session_factory()
    with session_factory() as db:
        settings = _build_settings()
        api = FakeTelegramApi()
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo)
        station = _seed_station(db, condo=condo)
        session = _seed_session(db, condo=condo, resident=resident, station=station, end_time=datetime.now(tz=UTC))
        service = ResidentTelegramNotificationService(
            db=db,
            settings=settings,
            bot_service=TelegramBotService(settings=settings, api_caller=api),
        )

        first = service.send_charging_completed(session=session, resident=resident, station=station)
        duplicate = service.send_charging_completed(session=session, resident=resident, station=station)

        rows = db.scalars(select(ResidentNotificationHistory)).all()
        assert first is not None
        assert duplicate is None
        assert len(rows) == 1
        assert rows[0].notification_type == NOTIFICATION_TYPE_CHARGING_COMPLETED
        assert rows[0].status == "sent"
        send_calls = [call for call in api.calls if call[0] == "sendMessage"]
        assert len(send_calls) == 1
        assert send_calls[0][1]["text"] == (
            "🔋 Ricarica completata\n\n"
            "Ti chiediamo di liberare il posto di ricarica.\n\n"
            "Persone in attesa: 0"
        )


def test_telegram_station_poller_creates_history_for_linked_residents() -> None:
    session_factory = _build_session_factory()
    with session_factory() as db:
        settings = _build_settings(telegram_bot_token="")
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo)
        station = _seed_station(db, condo=condo)
        poller = TelegramStationAvailabilityNotificationPoller(
            db_factory=session_factory,
            settings=settings,
            occupancy_fetcher=SequenceOccupancyFetcher(
                [
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="charging",
                            observed_at=datetime.now(tz=UTC) - timedelta(minutes=1),
                        )
                    ],
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="available",
                            observed_at=datetime.now(tz=UTC),
                        )
                    ],
                ]
            ),
        )

        assert poller.poll_once() == 0
        assert poller.poll_once() == 1

        rows = db.scalars(select(ResidentNotificationHistory)).all()
        assert len(rows) == 1
        assert rows[0].resident_app_user_id == resident.id
        assert rows[0].notification_type == NOTIFICATION_TYPE_STATION_AVAILABLE
        assert rows[0].status == "preview"


def test_telegram_station_poller_promotes_queue_only_when_station_is_free() -> None:
    session_factory = _build_session_factory()
    with session_factory() as db:
        settings = _build_settings(
            telegram_bot_token="",
            queue_assignment_start_hour=0,
            queue_assignment_end_hour=24,
        )
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo, username="queued-resident")
        station = _seed_station(db, condo=condo)
        _enable_queue(db, condo=condo)
        db.add(
            ChargingQueueEntry(
                condominium_id=condo.id,
                resident_app_user_id=resident.id,
                status=QUEUE_ENTRY_STATUS_WAITING,
                joined_at=datetime.now(tz=UTC) - timedelta(minutes=5),
            )
        )
        db.commit()

        poller = TelegramStationAvailabilityNotificationPoller(
            db_factory=session_factory,
            settings=settings,
            occupancy_fetcher=SequenceOccupancyFetcher(
                [
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="charging",
                            observed_at=datetime.now(tz=UTC) - timedelta(minutes=1),
                        )
                    ],
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="available",
                            observed_at=datetime.now(tz=UTC),
                        )
                    ],
                ]
            ),
        )

        assert poller.poll_once() == 0
        assert poller.poll_once() == 1

        rows = db.scalars(select(ResidentNotificationHistory).order_by(ResidentNotificationHistory.id.asc())).all()
        entry = db.scalar(select(ChargingQueueEntry).limit(1))
        assert entry is not None
        assert entry.status == QUEUE_ENTRY_STATUS_OFFERED
        assert entry.reserved_station_id == station.id
        assert entry.reserved_at is not None
        assert entry.reservation_expires_at is not None
        assert [row.notification_type for row in rows] == [NOTIFICATION_TYPE_QUEUE_TURN]


def test_telegram_station_poller_expires_reservation_and_offers_next_resident() -> None:
    session_factory = _build_session_factory()
    with session_factory() as db:
        settings = _build_settings(
            telegram_bot_token="",
            queue_assignment_start_hour=0,
            queue_assignment_end_hour=24,
        )
        condo = _seed_condo(db)
        first = _seed_resident(db, condo=condo, username="first")
        second = _seed_resident(db, condo=condo, username="second")
        station = _seed_station(db, condo=condo)
        _enable_queue(db, condo=condo)
        db.add_all(
            [
                ChargingQueueEntry(
                    condominium_id=condo.id,
                    resident_app_user_id=first.id,
                    status=QUEUE_ENTRY_STATUS_WAITING,
                    joined_at=datetime.now(tz=UTC) - timedelta(minutes=10),
                ),
                ChargingQueueEntry(
                    condominium_id=condo.id,
                    resident_app_user_id=second.id,
                    status=QUEUE_ENTRY_STATUS_WAITING,
                    joined_at=datetime.now(tz=UTC) - timedelta(minutes=9),
                ),
            ]
        )
        db.commit()

        poller = TelegramStationAvailabilityNotificationPoller(
            db_factory=session_factory,
            settings=settings,
            occupancy_fetcher=SequenceOccupancyFetcher(
                [
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="available",
                            observed_at=datetime.now(tz=UTC),
                        )
                    ]
                ]
            ),
        )

        assert poller.poll_once() == 1

        first_entry = db.scalar(
            select(ChargingQueueEntry)
            .where(ChargingQueueEntry.resident_app_user_id == first.id)
            .limit(1)
        )
        assert first_entry is not None
        first_entry.reservation_expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
        db.commit()

        assert poller.poll_once() == 2

        entries = db.scalars(select(ChargingQueueEntry).order_by(ChargingQueueEntry.id.asc())).all()
        assert entries[0].status == QUEUE_ENTRY_STATUS_LEFT
        assert entries[0].leave_reason == "reservation_expired"
        assert entries[1].status == QUEUE_ENTRY_STATUS_OFFERED

        rows = db.scalars(select(ResidentNotificationHistory).order_by(ResidentNotificationHistory.id.asc())).all()
        assert [row.notification_type for row in rows] == [
            NOTIFICATION_TYPE_QUEUE_TURN,
            NOTIFICATION_TYPE_QUEUE_RESERVATION_EXPIRED,
            NOTIFICATION_TYPE_QUEUE_TURN,
        ]


def test_telegram_station_poller_consumes_offer_only_for_matching_resident_on_assigned_station() -> None:
    session_factory = _build_session_factory()
    with session_factory() as db:
        settings = _build_settings(telegram_bot_token="", queue_assignment_start_hour=0, queue_assignment_end_hour=24)
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo, username="matched")
        _set_station_busy_enabled(db, resident=resident, enabled=False)
        station = _seed_station(db, condo=condo)
        reserved_at = datetime.now(tz=UTC) - timedelta(minutes=5)
        _seed_queue_entry(
            db,
            condo=condo,
            resident=resident,
            station=station,
            status=QUEUE_ENTRY_STATUS_OFFERED,
            joined_at=reserved_at - timedelta(minutes=1),
            reserved_at=reserved_at,
            reservation_expires_at=reserved_at + timedelta(minutes=30),
        )
        _seed_session(
            db,
            condo=condo,
            resident=resident,
            station=station,
            start_time=reserved_at + timedelta(minutes=1),
            end_time=reserved_at + timedelta(minutes=2),
        )

        poller = TelegramStationAvailabilityNotificationPoller(
            db_factory=session_factory,
            settings=settings,
            occupancy_fetcher=SequenceOccupancyFetcher(
                [
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="available",
                            observed_at=reserved_at,
                        )
                    ],
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="busy",
                            observed_at=reserved_at + timedelta(minutes=3),
                        )
                    ],
                ]
            ),
        )

        assert poller.poll_once() == 0
        poller.poll_once()

        entry = db.scalar(select(ChargingQueueEntry).limit(1))
        assert entry is not None
        assert entry.status == QUEUE_ENTRY_STATUS_LEFT
        assert entry.leave_reason == "charging_started"


def test_telegram_station_poller_cancels_offer_when_wrong_resident_takes_assigned_station() -> None:
    session_factory = _build_session_factory()
    with session_factory() as db:
        settings = _build_settings(telegram_bot_token="", queue_assignment_start_hour=0, queue_assignment_end_hour=24)
        condo = _seed_condo(db)
        offered_resident = _seed_resident(db, condo=condo, username="offered")
        other_resident = _seed_resident(db, condo=condo, username="other")
        _set_station_busy_enabled(db, resident=offered_resident, enabled=False)
        _set_station_busy_enabled(db, resident=other_resident, enabled=False)
        station = _seed_station(db, condo=condo)
        reserved_at = datetime.now(tz=UTC) - timedelta(minutes=5)
        _seed_queue_entry(
            db,
            condo=condo,
            resident=offered_resident,
            station=station,
            status=QUEUE_ENTRY_STATUS_OFFERED,
            joined_at=reserved_at - timedelta(minutes=1),
            reserved_at=reserved_at,
            reservation_expires_at=reserved_at + timedelta(minutes=30),
        )
        _seed_session(
            db,
            condo=condo,
            resident=other_resident,
            station=station,
            start_time=reserved_at + timedelta(minutes=1),
            end_time=reserved_at + timedelta(minutes=2),
        )

        poller = TelegramStationAvailabilityNotificationPoller(
            db_factory=session_factory,
            settings=settings,
            occupancy_fetcher=SequenceOccupancyFetcher(
                [
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="available",
                            observed_at=reserved_at,
                        )
                    ],
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="busy",
                            observed_at=reserved_at + timedelta(minutes=3),
                        )
                    ],
                ]
            ),
        )

        assert poller.poll_once() == 0
        assert poller.poll_once() == 1

        entry = db.scalar(select(ChargingQueueEntry).limit(1))
        rows = db.scalars(select(ResidentNotificationHistory).order_by(ResidentNotificationHistory.id.asc())).all()
        assert entry is not None
        assert entry.status == QUEUE_ENTRY_STATUS_LEFT
        assert entry.leave_reason == "reservation_cancelled_station_taken_by_other_resident"
        assert [row.notification_type for row in rows] == [NOTIFICATION_TYPE_QUEUE_RESERVATION_CANCELLED]


def test_telegram_station_poller_does_not_consume_offer_when_correct_resident_starts_on_wrong_station() -> None:
    session_factory = _build_session_factory()
    with session_factory() as db:
        settings = _build_settings(telegram_bot_token="", queue_assignment_start_hour=0, queue_assignment_end_hour=24)
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo, username="offered")
        _set_station_busy_enabled(db, resident=resident, enabled=False)
        assigned_station = _seed_station(db, condo=condo, host="192.168.1.200")
        other_station = _seed_station(db, condo=condo, host="192.168.1.201")
        reserved_at = datetime.now(tz=UTC) - timedelta(minutes=5)
        _seed_queue_entry(
            db,
            condo=condo,
            resident=resident,
            station=assigned_station,
            status=QUEUE_ENTRY_STATUS_OFFERED,
            joined_at=reserved_at - timedelta(minutes=1),
            reserved_at=reserved_at,
            reservation_expires_at=reserved_at + timedelta(minutes=30),
        )
        _seed_session(
            db,
            condo=condo,
            resident=resident,
            station=other_station,
            start_time=reserved_at + timedelta(minutes=1),
            end_time=reserved_at + timedelta(minutes=2),
        )

        poller = TelegramStationAvailabilityNotificationPoller(
            db_factory=session_factory,
            settings=settings,
            occupancy_fetcher=SequenceOccupancyFetcher(
                [
                    [
                        StationAvailabilitySnapshot(
                            station_id=other_station.id,
                            condominium_id=condo.id,
                            computed_status="available",
                            observed_at=reserved_at,
                        )
                    ],
                    [
                        StationAvailabilitySnapshot(
                            station_id=other_station.id,
                            condominium_id=condo.id,
                            computed_status="busy",
                            observed_at=reserved_at + timedelta(minutes=3),
                        )
                    ],
                ]
            ),
        )

        assert poller.poll_once() == 0
        assert poller.poll_once() == 0

        entry = db.scalar(select(ChargingQueueEntry).limit(1))
        assert entry is not None
        assert entry.status == QUEUE_ENTRY_STATUS_OFFERED
        assert entry.leave_reason is None
        assert entry.reserved_station_id == assigned_station.id


def test_telegram_station_poller_cancels_offer_when_station_becomes_busy_without_resident_mapping() -> None:
    session_factory = _build_session_factory()
    with session_factory() as db:
        settings = _build_settings(telegram_bot_token="", queue_assignment_start_hour=0, queue_assignment_end_hour=24)
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo, username="offered")
        _set_station_busy_enabled(db, resident=resident, enabled=False)
        station = _seed_station(db, condo=condo)
        reserved_at = datetime.now(tz=UTC) - timedelta(minutes=5)
        _seed_queue_entry(
            db,
            condo=condo,
            resident=resident,
            station=station,
            status=QUEUE_ENTRY_STATUS_OFFERED,
            joined_at=reserved_at - timedelta(minutes=1),
            reserved_at=reserved_at,
            reservation_expires_at=reserved_at + timedelta(minutes=30),
        )
        _seed_session(
            db,
            condo=condo,
            resident=resident,
            station=station,
            start_time=reserved_at + timedelta(minutes=1),
            end_time=reserved_at + timedelta(minutes=2),
            mapped_app_user_id=None,
        )

        poller = TelegramStationAvailabilityNotificationPoller(
            db_factory=session_factory,
            settings=settings,
            occupancy_fetcher=SequenceOccupancyFetcher(
                [
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="available",
                            observed_at=reserved_at,
                        )
                    ],
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="busy",
                            observed_at=reserved_at + timedelta(minutes=3),
                        )
                    ],
                ]
            ),
        )

        assert poller.poll_once() == 0
        assert poller.poll_once() == 1

        entry = db.scalar(select(ChargingQueueEntry).limit(1))
        rows = db.scalars(select(ResidentNotificationHistory).order_by(ResidentNotificationHistory.id.asc())).all()
        assert entry is not None
        assert entry.status == QUEUE_ENTRY_STATUS_LEFT
        assert entry.leave_reason == "reservation_cancelled_station_busy_without_resident_mapping"
        assert [row.notification_type for row in rows] == [NOTIFICATION_TYPE_QUEUE_RESERVATION_CANCELLED]


def test_telegram_station_poller_sends_completion_reminder_when_space_stays_busy() -> None:
    session_factory = _build_session_factory()
    with session_factory() as db:
        settings = _build_settings(
            telegram_bot_token="",
            queue_assignment_start_hour=0,
            queue_assignment_end_hour=24,
            notification_recency_minutes=120,
        )
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo)
        station = _seed_station(db, condo=condo)
        session = _seed_session(
            db,
            condo=condo,
            resident=resident,
            station=station,
            end_time=datetime.now(tz=UTC) - timedelta(minutes=31),
        )
        poller = TelegramStationAvailabilityNotificationPoller(
            db_factory=session_factory,
            settings=settings,
            occupancy_fetcher=SequenceOccupancyFetcher(
                [
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="busy",
                            observed_at=datetime.now(tz=UTC),
                        )
                    ]
                ]
            ),
        )

        assert poller.poll_once() == 1

        rows = db.scalars(select(ResidentNotificationHistory).order_by(ResidentNotificationHistory.id.asc())).all()
        assert len(rows) == 1
        assert rows[0].notification_type == NOTIFICATION_TYPE_CHARGING_COMPLETED_REMINDER
        assert rows[0].dedupe_key == f"session:{session.id}:reminder:30"


def test_agent_status_poller_sends_offline_and_recovered_once() -> None:
    session_factory = _build_session_factory()
    with session_factory() as db:
        settings = _build_settings(telegram_bot_token="", telegram_agent_offline_threshold_seconds=180)
        condo = _seed_condo(db)
        _seed_resident(db, condo=condo)
        baseline = datetime.now(tz=UTC)
        state = AgentState(
            condominium_id=condo.id,
            agent_id="agent-1",
            last_heartbeat_at=baseline,
        )
        db.add(state)
        db.commit()
        db.refresh(state)

        poller = TelegramAgentStatusNotificationPoller(db_factory=session_factory, settings=settings)

        assert poller.poll_once(now=baseline + timedelta(seconds=30)) == 0
        assert poller.poll_once(now=baseline + timedelta(seconds=181)) == 1
        assert poller.poll_once(now=baseline + timedelta(seconds=220)) == 0

        state.last_heartbeat_at = baseline + timedelta(seconds=220)
        db.commit()

        assert poller.poll_once(now=baseline + timedelta(seconds=230)) == 1

        rows = db.scalars(
            select(ResidentNotificationHistory).order_by(ResidentNotificationHistory.created_at.asc(), ResidentNotificationHistory.id.asc())
        ).all()
        assert [row.notification_type for row in rows] == [
            NOTIFICATION_TYPE_AGENT_OFFLINE,
            NOTIFICATION_TYPE_AGENT_RECOVERED,
        ]


def test_api_resident_profile_and_admin_settings_include_telegram_fields(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_USERNAME", "CondoChargeBot")
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_TOKEN", "")

    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        admin = AppUser(
            condominium_id=condo.id,
            username="admin",
            password_hash=hash_password("password123"),
            role=AppUserRole.ADMIN.value,
            is_active=1,
        )
        resident = AppUser(
            condominium_id=condo.id,
            username="resident",
            email="resident@example.com",
            telegram_chat_id="555",
            telegram_username="resident_bot",
            telegram_linked_at=datetime.now(tz=UTC),
            password_hash=hash_password("password123"),
            role=AppUserRole.RESIDENT.value,
            is_active=1,
        )
        db.add_all([admin, resident])
        db.flush()
        db.add(
            ResidentNotificationPreferences(
                condominium_id=condo.id,
                app_user_id=resident.id,
                charging_completed=1,
                station_available=1,
                    station_busy=1,
                station_back_online=0,
                agent_offline=1,
                agent_recovered=1,
            )
        )
        db.commit()

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    resident_login = client.post(
        "/api/v1/auth/login",
        json={"username": "resident", "password": "password123", "condominium": "Test Condo"},
    )
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "password123", "condominium": "Test Condo"},
    )
    resident_headers = {"Authorization": f"Bearer {resident_login.json()['token']['access_token']}"}
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['token']['access_token']}"}

    profile = client.get("/api/v1/resident/profile", headers=resident_headers)
    settings = client.get("/api/v1/admin/settings", headers=admin_headers)
    telegram_status = client.get("/api/v1/admin/telegram/status", headers=admin_headers)

    assert profile.status_code == 200
    assert profile.json()["telegram"]["linked"] is True
    assert profile.json()["notification_preferences"]["station_busy"] is True
    assert profile.json()["notification_preferences"]["agent_offline"] is True

    assert settings.status_code == 200
    assert settings.json()["telegram_station_available_enabled"] is True
    assert settings.json()["telegram_station_busy_enabled"] is False
    assert settings.json()["telegram_agent_recovered_enabled"] is True

    assert telegram_status.status_code == 200
    assert telegram_status.json()["bot_username"] == "CondoChargeBot"

    get_settings.cache_clear()


def test_telegram_webhook_links_resident(monkeypatch) -> None:
    def fake_send_message(self: TelegramBotService, *, chat_id: str, text: str) -> TelegramSendResult:
        del self, chat_id, text
        return TelegramSendResult(message_id="1")

    monkeypatch.setattr(TelegramBotService, "send_message", fake_send_message)
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_USERNAME", "CondoChargeBot")
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_TOKEN", "telegram-token")

    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo, linked_telegram=False)
        resident.telegram_username = None
        resident.telegram_linked_at = None
        db.commit()
        settings = _build_settings()
        link_service = ResidentTelegramLinkService(
            db=db,
            settings=settings,
            deep_link_builder=lambda token: f"https://t.me/CondoChargeBot?start={token}",
        )
        issue = link_service.issue_link(resident=resident)

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/telegram/webhook",
        json={
            "message": {
                "text": f"/start {issue.token}",
                "chat": {"id": 777},
                "from": {"username": "resident_bot"},
            }
        },
    )
    assert response.status_code == 200

    with session_factory() as db:
        refreshed = db.scalar(select(AppUser).where(AppUser.username == "resident"))
        assert refreshed is not None
        assert refreshed.telegram_chat_id == "777"
        assert refreshed.telegram_username == "resident_bot"

    get_settings.cache_clear()


def test_telegram_webhook_links_resident_even_if_confirmation_send_fails(monkeypatch) -> None:
    def failing_send_message(self: TelegramBotService, *, chat_id: str, text: str) -> TelegramSendResult:
        del self, chat_id, text
        raise TelegramDeliveryError("chat not found")

    monkeypatch.setattr(TelegramBotService, "send_message", failing_send_message)
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_USERNAME", "CondoChargeBot")
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_TOKEN", "telegram-token")

    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo, linked_telegram=False)
        resident.telegram_username = None
        resident.telegram_linked_at = None
        db.commit()
        settings = _build_settings()
        link_service = ResidentTelegramLinkService(
            db=db,
            settings=settings,
            deep_link_builder=lambda token: f"https://t.me/CondoChargeBot?start={token}",
        )
        issue = link_service.issue_link(resident=resident)

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/telegram/webhook",
        json={
            "message": {
                "text": f"/start {issue.token}",
                "chat": {"id": 778},
                "from": {"username": "resident_bot"},
            }
        },
    )
    assert response.status_code == 200

    with session_factory() as db:
        refreshed = db.scalar(select(AppUser).where(AppUser.username == "resident"))
        assert refreshed is not None
        assert refreshed.telegram_chat_id == "778"
        assert refreshed.telegram_username == "resident_bot"

    get_settings.cache_clear()


def test_telegram_webhook_returns_ok_for_expired_token_even_if_failure_send_fails(monkeypatch) -> None:
    def failing_send_message(self: TelegramBotService, *, chat_id: str, text: str) -> TelegramSendResult:
        del self, chat_id, text
        raise TelegramDeliveryError("chat not found")

    monkeypatch.setattr(TelegramBotService, "send_message", failing_send_message)
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_USERNAME", "CondoChargeBot")
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_TOKEN", "telegram-token")

    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo, linked_telegram=False)
        resident.telegram_username = None
        resident.telegram_linked_at = None
        db.commit()
        settings = _build_settings()
        link_service = ResidentTelegramLinkService(
            db=db,
            settings=settings,
            deep_link_builder=lambda token: f"https://t.me/CondoChargeBot?start={token}",
        )
        issue = link_service.issue_link(resident=resident)
        token_row = db.scalar(select(ResidentTelegramLinkToken).where(ResidentTelegramLinkToken.app_user_id == resident.id))
        assert token_row is not None
        token_row.expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
        db.commit()

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/telegram/webhook",
        json={
            "message": {
                "text": f"/start {issue.token}",
                "chat": {"id": 779},
                "from": {"username": "resident_bot"},
            }
        },
    )
    assert response.status_code == 200

    with session_factory() as db:
        refreshed = db.scalar(select(AppUser).where(AppUser.username == "resident"))
        assert refreshed is not None
        assert refreshed.telegram_chat_id is None
        assert refreshed.telegram_username is None
        assert refreshed.telegram_linked_at is None

    get_settings.cache_clear()


def test_telegram_webhook_help_handles_unknown_and_linked_chats(monkeypatch) -> None:
    sent_texts: list[str] = []

    def fake_send_message(self: TelegramBotService, *, chat_id: str, text: str) -> TelegramSendResult:
        del self, chat_id
        sent_texts.append(text)
        return TelegramSendResult(message_id=str(len(sent_texts)))

    monkeypatch.setattr(TelegramBotService, "send_message", fake_send_message)
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_USERNAME", "CondoChargeBot")
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_TOKEN", "telegram-token")

    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        _seed_resident(db, condo=condo)

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    unknown = client.post("/api/v1/telegram/webhook", json={"message": {"text": "/help", "chat": {"id": 987654}}})
    linked = client.post("/api/v1/telegram/webhook", json={"message": {"text": "/help", "chat": {"id": 123456}}})

    assert unknown.status_code == 200
    assert linked.status_code == 200
    assert "Genera link Telegram" in sent_texts[0]
    assert "/history" in sent_texts[0]
    assert "/status" in sent_texts[1]
    assert "/history" in sent_texts[1]

    get_settings.cache_clear()


def test_telegram_webhook_start_for_linked_resident_pins_regulations_best_effort(monkeypatch) -> None:
    sent_texts: list[str] = []
    pinned_ids: list[str] = []

    def fake_send_message(
        self: TelegramBotService,
        *,
        chat_id: str,
        text: str,
        reply_markup=None,
    ) -> TelegramSendResult:
        del self, chat_id, reply_markup
        sent_texts.append(text)
        return TelegramSendResult(message_id=str(len(sent_texts)))

    def fake_pin_message(self: TelegramBotService, *, chat_id: str, message_id: str, disable_notification: bool = True) -> None:
        del self, chat_id, disable_notification
        pinned_ids.append(message_id)

    monkeypatch.setattr(TelegramBotService, "send_message", fake_send_message)
    monkeypatch.setattr(TelegramBotService, "pin_message", fake_pin_message)
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_USERNAME", "CondoChargeBot")
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_TOKEN", "telegram-token")

    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        _seed_resident(db, condo=condo)

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    response = client.post("/api/v1/telegram/webhook", json={"message": {"text": "/start", "chat": {"id": 123456}}})

    assert response.status_code == 200
    assert len(sent_texts) == 2
    assert "/status" in sent_texts[0]
    assert "📜 Regolamento CondoCharge" in sent_texts[1]
    assert pinned_ids == ["2"]

    get_settings.cache_clear()


def test_telegram_webhook_regulations_pin_failure_does_not_fail_webhook(monkeypatch) -> None:
    sent_texts: list[str] = []
    pin_attempts: list[str] = []

    def fake_send_message(
        self: TelegramBotService,
        *,
        chat_id: str,
        text: str,
        reply_markup=None,
    ) -> TelegramSendResult:
        del self, chat_id, reply_markup
        sent_texts.append(text)
        return TelegramSendResult(message_id="42")

    def failing_pin_message(
        self: TelegramBotService,
        *,
        chat_id: str,
        message_id: str,
        disable_notification: bool = True,
    ) -> None:
        del self, chat_id, disable_notification
        pin_attempts.append(message_id)
        raise TelegramDeliveryError("pin failed")

    monkeypatch.setattr(TelegramBotService, "send_message", fake_send_message)
    monkeypatch.setattr(TelegramBotService, "pin_message", failing_pin_message)
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_USERNAME", "CondoChargeBot")
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_TOKEN", "telegram-token")

    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        _seed_resident(db, condo=condo)

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/telegram/webhook",
        json={"message": {"text": "Regolamento", "chat": {"id": 123456}}},
    )

    assert response.status_code == 200
    assert sent_texts == ["📜 Regolamento CondoCharge\n\nCondominio: Test Condo\n\n• Le assegnazioni seguono l'ordine della coda.\n• Hai 30 minuti per iniziare la ricarica.\n• Se non inizi entro il tempo previsto perdi il turno.\n• Quando la ricarica termina, libera il posto appena possibile.\n• Le prenotazioni sono attive dalle 08:00 alle 22:00.\n• Le informazioni degli altri residenti non sono visibili."]
    assert pin_attempts == ["42"]

    get_settings.cache_clear()


def test_status_message_uses_rome_time_and_hides_resident_details(monkeypatch) -> None:
    import condocharge.api.v1.telegram as telegram_api

    observed_at = datetime.now(tz=UTC).replace(second=0, microsecond=0)
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_AGENT_OCCUPANCY_SOURCE", "db")
    monkeypatch.setenv("CONDOCHARGE_AGENT_STALE_AFTER_SECONDS", "600")

    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo)
        station = _seed_station(db, condo=condo)
        _seed_session(db, condo=condo, resident=resident, station=station, end_time=observed_at)

        monkeypatch.setattr(
            telegram_api,
            "_stations_db_occupancy",
            lambda *, stations: [
                StationOccupancyResponse(
                    station_id=stations[0].id,
                    host=stations[0].host,
                    connector_status="charging",
                    computed_status="busy",
                    last_checked_at=observed_at,
                    source="db",
                )
            ],
        )

        message = telegram_api._status_message_for_resident(db=db, resident=resident)

    assert "Garage A: 🔴 Occupata" in message
    assert (
        f"Ultimo aggiornamento: {observed_at.astimezone(ZoneInfo('Europe/Rome')).strftime('%Y-%m-%d %H:%M')}"
        in message
    )
    assert "ultimo residente" not in message.lower()
    assert "sessione attiva" not in message.lower()

    get_settings.cache_clear()


def test_status_message_hides_stale_timestamp(monkeypatch) -> None:
    import condocharge.api.v1.telegram as telegram_api

    stale_observed_at = datetime.now(tz=UTC) - timedelta(minutes=10)
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_AGENT_OCCUPANCY_SOURCE", "db")
    monkeypatch.setenv("CONDOCHARGE_AGENT_STALE_AFTER_SECONDS", "60")

    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo)
        station = _seed_station(db, condo=condo)

        monkeypatch.setattr(
            telegram_api,
            "_stations_db_occupancy",
            lambda *, stations: [
                StationOccupancyResponse(
                    station_id=stations[0].id,
                    host=stations[0].host,
                    connector_status="available",
                    computed_status="free",
                    last_checked_at=stale_observed_at,
                    source="db",
                )
            ],
        )

        message = telegram_api._status_message_for_resident(db=db, resident=resident)

    assert "Ultimo aggiornamento: dati in aggiornamento" in message
    assert stale_observed_at.astimezone(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M") not in message

    get_settings.cache_clear()


def test_telegram_webhook_status_command_sends_status(monkeypatch) -> None:
    sent_texts: list[str] = []

    def fake_send_message(self: TelegramBotService, *, chat_id: str, text: str) -> TelegramSendResult:
        del self, chat_id
        sent_texts.append(text)
        return TelegramSendResult(message_id="1")

    monkeypatch.setattr(TelegramBotService, "send_message", fake_send_message)
    import condocharge.api.v1.telegram as telegram_api

    monkeypatch.setattr(telegram_api, "_status_message_for_resident", lambda *, db, resident: "status output")
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_USERNAME", "CondoChargeBot")
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_TOKEN", "telegram-token")

    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        _seed_resident(db, condo=condo)

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    response = client.post("/api/v1/telegram/webhook", json={"message": {"text": "/status", "chat": {"id": 123456}}})

    assert response.status_code == 200
    assert sent_texts == ["status output"]

    get_settings.cache_clear()


def test_telegram_webhook_history_command_sends_last_10_sessions(monkeypatch) -> None:
    sent_texts: list[str] = []

    def fake_send_message(self: TelegramBotService, *, chat_id: str, text: str) -> TelegramSendResult:
        del self, chat_id
        sent_texts.append(text)
        return TelegramSendResult(message_id="1")

    monkeypatch.setattr(TelegramBotService, "send_message", fake_send_message)
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_USERNAME", "CondoChargeBot")
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_TOKEN", "telegram-token")

    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        resident = _seed_resident(db, condo=condo)
        station = _seed_station(db, condo=condo)
        rfid = RfidUser(
            condominium_id=condo.id,
            app_user_id=resident.id,
            rfid_id="RFID-HISTORY",
            name="History card",
        )
        db.add(rfid)
        db.flush()
        base_end_time = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
        for index in range(12):
            end_time = base_end_time + timedelta(days=index)
            db.add(
                ChargingSession(
                    condominium_id=condo.id,
                    source_key=f"history-{index}",
                    station_id=station.id,
                    rfid_user_id=rfid.id,
                    start_time=end_time - timedelta(hours=2),
                    end_time=end_time,
                    energy_wh=(index + 1) * 1000,
                    total_minutes=120,
                    charging_minutes=100,
                    idle_minutes=20,
                    plug_type="Type2",
                )
            )
        db.commit()

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    response = client.post("/api/v1/telegram/webhook", json={"message": {"text": "/history", "chat": {"id": 123456}}})

    assert response.status_code == 200
    assert len(sent_texts) == 1
    assert "Ultime 10 sessioni di ricarica:" in sent_texts[0]
    assert "2026-01-12 09:00 - 12 kWh - €3.60" in sent_texts[0]
    assert "2026-01-03 09:00 - 3 kWh - €0.90" in sent_texts[0]
    assert "2026-01-02 09:00" not in sent_texts[0]
    assert "2026-01-01 09:00" not in sent_texts[0]

    get_settings.cache_clear()


def test_telegram_webhook_test_command_creates_audit_row(monkeypatch) -> None:
    def fake_send_message(self: TelegramBotService, *, chat_id: str, text: str) -> TelegramSendResult:
        del self, chat_id, text
        return TelegramSendResult(message_id="55")

    monkeypatch.setattr(TelegramBotService, "send_message", fake_send_message)
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_USERNAME", "CondoChargeBot")
    monkeypatch.setenv("CONDOCHARGE_TELEGRAM_BOT_TOKEN", "telegram-token")

    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        _seed_resident(db, condo=condo)

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    response = client.post("/api/v1/telegram/webhook", json={"message": {"text": "/test", "chat": {"id": 123456}}})

    assert response.status_code == 200
    with session_factory() as db:
        row = db.scalar(
            select(ResidentNotificationHistory)
            .where(ResidentNotificationHistory.notification_type == NOTIFICATION_TYPE_COMMAND_TEST)
            .limit(1)
        )
        assert row is not None
        assert row.status == "sent"
        assert row.provider_message_id == "55"

    get_settings.cache_clear()


def test_telegram_station_poller_creates_busy_and_back_online_history() -> None:
    session_factory = _build_session_factory()
    with session_factory() as db:
        settings = _build_settings(telegram_bot_token="")
        condo = _seed_condo(db)
        condo.telegram_station_busy_enabled = 1
        condo.telegram_station_back_online_enabled = 1
        db.commit()
        resident = _seed_resident(db, condo=condo)
        resident_prefs = db.scalar(
            select(ResidentNotificationPreferences).where(ResidentNotificationPreferences.app_user_id == resident.id).limit(1)
        )
        assert resident_prefs is not None
        resident_prefs.station_back_online = 1
        db.commit()
        station = _seed_station(db, condo=condo)
        poller = TelegramStationAvailabilityNotificationPoller(
            db_factory=session_factory,
            settings=settings,
            occupancy_fetcher=SequenceOccupancyFetcher(
                [
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="available",
                            observed_at=datetime.now(tz=UTC) - timedelta(minutes=3),
                        )
                    ],
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="busy",
                            observed_at=datetime.now(tz=UTC) - timedelta(minutes=2),
                        )
                    ],
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="offline",
                            observed_at=datetime.now(tz=UTC) - timedelta(minutes=1),
                        )
                    ],
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="available",
                            observed_at=datetime.now(tz=UTC),
                        )
                    ],
                ]
            ),
        )

        assert poller.poll_once() == 0
        assert poller.poll_once() == 1
        assert poller.poll_once() == 0
        assert poller.poll_once() == 1

        rows = db.scalars(
            select(ResidentNotificationHistory).order_by(ResidentNotificationHistory.created_at.asc(), ResidentNotificationHistory.id.asc())
        ).all()
        assert [row.notification_type for row in rows] == [
            NOTIFICATION_TYPE_STATION_BUSY,
            NOTIFICATION_TYPE_STATION_BACK_ONLINE,
        ]
        assert all(row.status == "preview" for row in rows)
