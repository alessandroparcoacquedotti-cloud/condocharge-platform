from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.api.deps import get_db_session
from condocharge.app.services.resident_notification_service import StationAvailabilitySnapshot
from condocharge.app.services.resident_telegram_link_service import ResidentTelegramLinkService
from condocharge.app.services.telegram_bot_service import TelegramBotService, TelegramSendResult
from condocharge.app.services.telegram_notification_service import (
    NOTIFICATION_TYPE_AGENT_OFFLINE,
    NOTIFICATION_TYPE_AGENT_RECOVERED,
    NOTIFICATION_TYPE_CHARGING_COMPLETED,
    NOTIFICATION_TYPE_STATION_AVAILABLE,
    ResidentTelegramNotificationService,
    TelegramAgentStatusNotificationPoller,
    TelegramStationAvailabilityNotificationPoller,
)
from condocharge.core.config import Settings, get_settings
from condocharge.core.security import hash_password
from condocharge.db.base import Base
from condocharge.main import create_app
from condocharge.models.charging import AgentState, ChargingSession, ChargingStation, RfidUser
from condocharge.models.tenancy import (
    AppUser,
    AppUserRole,
    Condominium,
    ResidentNotificationHistory,
    ResidentNotificationPreferences,
    ResidentTelegramLinkToken,
)


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
        telegram_chat_id="123456" if linked_telegram else None,
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
    end_time: datetime,
) -> ChargingSession:
    rfid = RfidUser(
        condominium_id=condo.id,
        app_user_id=resident.id,
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
        start_time=end_time - timedelta(hours=1),
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
        assert len([call for call in api.calls if call[0] == "sendMessage"]) == 1


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
    assert profile.json()["notification_preferences"]["agent_offline"] is True

    assert settings.status_code == 200
    assert settings.json()["telegram_station_available_enabled"] is True
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
