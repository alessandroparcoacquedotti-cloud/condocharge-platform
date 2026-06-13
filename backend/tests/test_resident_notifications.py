from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.app.integrations.legrand.driver import ChargingSession as LegrandChargingSession
from condocharge.app.services.resident_notification_service import (
    NOTIFICATION_TYPE_CHARGING_COMPLETED,
    NOTIFICATION_TYPE_STATION_AVAILABLE,
    STATUS_PREVIEW,
    ResidentNotificationService,
    StationAvailabilityNotificationPoller,
    StationAvailabilitySnapshot,
)
from condocharge.app.services.session_sync_service import SessionSyncService
from condocharge.core.config import Settings
from condocharge.db.base import Base
from condocharge.models.charging import ChargingSession, ChargingStation, RfidUser
from condocharge.models.tenancy import (
    AppUser,
    AppUserRole,
    Condominium,
    ResidentEmailNotification,
    ResidentNotificationPreferences,
)


class FakeDriver:
    def __init__(self, sessions_by_host: dict[str, list[LegrandChargingSession]]) -> None:
        self._sessions_by_host = sessions_by_host

    def login(self, host: str, username: str, password: str) -> None:
        return None

    def sync_charge_sessions(self, host: str) -> list[LegrandChargingSession]:
        return self._sessions_by_host[host]


class SequenceOccupancyFetcher:
    def __init__(self, snapshots_by_call: list[Sequence[StationAvailabilitySnapshot]]) -> None:
        self._snapshots_by_call = snapshots_by_call
        self._index = 0

    def __call__(self, *, db: Session) -> Sequence[StationAvailabilitySnapshot]:
        del db
        value = self._snapshots_by_call[min(self._index, len(self._snapshots_by_call) - 1)]
        self._index += 1
        return value


def _build_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)
    return testing_session_local


def _build_settings() -> Settings:
    return Settings(
        email_enabled=False,
        notifications_enabled=True,
        notification_recency_minutes=30,
        notification_station_cooldown_minutes=15,
        notification_resident_cooldown_minutes=5,
    )


def _seed_condo(db: Session, *, name: str = "Condo A") -> Condominium:
    condo = Condominium(name=name)
    db.add(condo)
    db.commit()
    db.refresh(condo)
    return condo


def _seed_station(db: Session, *, condo: Condominium, host: str, name: str | None = None) -> ChargingStation:
    station = ChargingStation(condominium_id=condo.id, host=host, vendor="legrand_greenup", name=name)
    db.add(station)
    db.commit()
    db.refresh(station)
    return station


def _seed_resident(
    db: Session,
    *,
    condo: Condominium,
    username: str,
    email: str,
    charging_completed: bool = True,
    station_available: bool = True,
) -> AppUser:
    resident = AppUser(
        condominium_id=condo.id,
        username=username,
        email=email,
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
            charging_completed=1 if charging_completed else 0,
            station_available=1 if station_available else 0,
            station_back_online=0,
        )
    )
    db.commit()
    db.refresh(resident)
    return resident


def _seed_session(
    db: Session,
    *,
    condo: Condominium,
    station: ChargingStation,
    resident: AppUser,
    end_time: datetime,
) -> ChargingSession:
    rfid_user = RfidUser(
        condominium_id=condo.id,
        app_user_id=resident.id,
        rfid_id=f"RFID-{resident.id}",
        name=resident.username,
    )
    db.add(rfid_user)
    db.flush()
    session = ChargingSession(
        condominium_id=condo.id,
        source_key=f"source-{resident.id}-{int(end_time.timestamp())}",
        station_id=station.id,
        rfid_user_id=rfid_user.id,
        start_time=end_time - timedelta(hours=1),
        end_time=end_time,
        energy_wh=5200,
        total_minutes=60,
        charging_minutes=55,
        idle_minutes=5,
        plug_type="Type2",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def test_dedupe_prevents_duplicate_charging_completed_email() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        settings = _build_settings()
        condo = _seed_condo(db)
        station = _seed_station(db, condo=condo, host="192.168.1.200", name="Garage A")
        resident = _seed_resident(db, condo=condo, username="alice", email="alice@example.com")
        session = _seed_session(
            db,
            condo=condo,
            station=station,
            resident=resident,
            end_time=datetime.now(tz=timezone.utc) - timedelta(minutes=5),
        )
        service = ResidentNotificationService(db=db, settings=settings)

        notification = service.send_charging_completed(session=session, resident=resident, station=station)
        duplicate = service.send_charging_completed(session=session, resident=resident, station=station)

        rows = db.scalars(select(ResidentEmailNotification)).all()
        assert notification is not None
        assert duplicate is None
        assert len(rows) == 1
        assert rows[0].notification_type == NOTIFICATION_TYPE_CHARGING_COMPLETED
        assert rows[0].dedupe_key == f"session:{session.id}"
        assert rows[0].status == STATUS_PREVIEW
    finally:
        db.close()


def test_historical_session_import_does_not_notify() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        now = datetime.now(tz=timezone.utc)
        condo = _seed_condo(db)
        _seed_resident(db, condo=condo, username="RFID-1", email="resident@example.com")
        driver = FakeDriver(
            {
                "192.168.1.200": [
                    LegrandChargingSession(
                        start_time=now - timedelta(days=2, hours=1),
                        end_time=now - timedelta(days=2),
                        energy_wh=5000,
                        total_minutes=60,
                        charging_minutes=55,
                        idle_minutes=5,
                        plug_type="Type2",
                        rfid_id="RFID-1",
                    )
                ]
            }
        )
        service = SessionSyncService(db=db, driver=driver, settings=_build_settings())

        result = service.sync_hosts(
            condominium_id=condo.id,
            hosts=["192.168.1.200"],
            username="user",
            password="pass",
        )

        notifications = db.scalars(select(ResidentEmailNotification)).all()
        assert result.errors == []
        assert result.sessions_imported == 1
        assert notifications == []
    finally:
        db.close()


def test_recent_session_import_creates_preview_notification_when_smtp_disabled() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        now = datetime.now(tz=timezone.utc)
        condo = _seed_condo(db)
        _seed_resident(db, condo=condo, username="RFID-2", email="resident@example.com")
        driver = FakeDriver(
            {
                "192.168.1.200": [
                    LegrandChargingSession(
                        start_time=now - timedelta(minutes=70),
                        end_time=now - timedelta(minutes=10),
                        energy_wh=6400,
                        total_minutes=60,
                        charging_minutes=55,
                        idle_minutes=5,
                        plug_type="Type2",
                        rfid_id="RFID-2",
                    )
                ]
            }
        )
        service = SessionSyncService(db=db, driver=driver, settings=_build_settings())

        result = service.sync_hosts(
            condominium_id=condo.id,
            hosts=["192.168.1.200"],
            username="user",
            password="pass",
        )

        notification = db.scalar(select(ResidentEmailNotification))
        assert result.errors == []
        assert result.sessions_imported == 1
        assert notification is not None
        assert notification.notification_type == NOTIFICATION_TYPE_CHARGING_COMPLETED
        assert notification.status == STATUS_PREVIEW
    finally:
        db.close()


def test_station_available_transition_creates_preview_notifications() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        settings = _build_settings()
        condo = _seed_condo(db)
        station = _seed_station(db, condo=condo, host="192.168.1.200", name="Garage A")
        resident_a = _seed_resident(db, condo=condo, username="alice", email="alice@example.com")
        resident_b = _seed_resident(db, condo=condo, username="bob", email="bob@example.com")
        poller = StationAvailabilityNotificationPoller(
            db_factory=session_factory,
            settings=settings,
            occupancy_fetcher=SequenceOccupancyFetcher(
                [
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="charging",
                            observed_at=datetime.now(tz=timezone.utc) - timedelta(minutes=1),
                        )
                    ],
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="available",
                            observed_at=datetime.now(tz=timezone.utc),
                        )
                    ],
                ]
            ),
        )

        assert poller.poll_once() == 0
        created = poller.poll_once()

        notifications = db.scalars(
            select(ResidentEmailNotification)
            .where(ResidentEmailNotification.notification_type == NOTIFICATION_TYPE_STATION_AVAILABLE)
            .order_by(ResidentEmailNotification.resident_app_user_id.asc())
        ).all()
        assert created == 2
        assert [n.resident_app_user_id for n in notifications] == [resident_a.id, resident_b.id]
        assert all(n.status == STATUS_PREVIEW for n in notifications)
    finally:
        db.close()


def test_cooldown_prevents_station_available_spam() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        settings = _build_settings()
        now = datetime.now(tz=timezone.utc)
        condo = _seed_condo(db)
        station_a = _seed_station(db, condo=condo, host="192.168.1.200")
        station_b = _seed_station(db, condo=condo, host="192.168.1.201")
        resident_a = _seed_resident(db, condo=condo, username="alice", email="alice@example.com")
        resident_b = _seed_resident(db, condo=condo, username="bob", email="bob@example.com")
        db.add(
            ResidentEmailNotification(
                condominium_id=condo.id,
                resident_app_user_id=resident_a.id,
                notification_type=NOTIFICATION_TYPE_STATION_AVAILABLE,
                dedupe_key=f"station:{station_a.id}:transition:{now.isoformat()}:resident:{resident_a.id}",
                status=STATUS_PREVIEW,
                created_at=now,
            )
        )
        db.commit()
        service = ResidentNotificationService(db=db, settings=settings)

        station_cooldown = service.send_station_available(
            condominium_id=condo.id,
            resident=resident_b,
            station=station_a,
            observed_at=now + timedelta(minutes=1),
        )
        resident_cooldown = service.send_station_available(
            condominium_id=condo.id,
            resident=resident_a,
            station=station_b,
            observed_at=now + timedelta(minutes=2),
        )

        notifications = db.scalars(
            select(ResidentEmailNotification).where(
                ResidentEmailNotification.notification_type == NOTIFICATION_TYPE_STATION_AVAILABLE
            )
        ).all()
        assert station_cooldown is None
        assert resident_cooldown is None
        assert len(notifications) == 1
    finally:
        db.close()


def test_preferences_are_respected_for_station_available_notifications() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        settings = _build_settings()
        condo = _seed_condo(db)
        station = _seed_station(db, condo=condo, host="192.168.1.200")
        opted_in = _seed_resident(db, condo=condo, username="alice", email="alice@example.com", station_available=True)
        _seed_resident(db, condo=condo, username="bob", email="bob@example.com", station_available=False)
        poller = StationAvailabilityNotificationPoller(
            db_factory=session_factory,
            settings=settings,
            occupancy_fetcher=SequenceOccupancyFetcher(
                [
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="offline",
                            observed_at=datetime.now(tz=timezone.utc) - timedelta(minutes=1),
                        )
                    ],
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="available",
                            observed_at=datetime.now(tz=timezone.utc),
                        )
                    ],
                ]
            ),
        )

        poller.poll_once()
        created = poller.poll_once()

        notifications = db.scalars(select(ResidentEmailNotification)).all()
        assert created == 1
        assert len(notifications) == 1
        assert notifications[0].resident_app_user_id == opted_in.id
    finally:
        db.close()
