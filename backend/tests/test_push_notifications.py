from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.api.deps import get_db_session
from condocharge.app.services.push_notification_service import (
    CHANNEL_WEB_PUSH,
    NOTIFICATION_TYPE_QUEUE_NEXT_IN_LINE,
    PushAgentStatusNotificationPoller,
    PushNotificationService,
    PushStationNotificationPoller,
)
from condocharge.app.services.resident_notification_service import (
    NOTIFICATION_TYPE_CHARGING_COMPLETED,
    NOTIFICATION_TYPE_STATION_AVAILABLE,
    StationAvailabilitySnapshot,
)
from condocharge.core.config import Settings
from condocharge.core.security import hash_password
from condocharge.db.base import Base
from condocharge.main import create_app
from condocharge.models.charging import AgentState, ChargingSession, ChargingStation, RfidUser
from condocharge.models.queue import ChargingQueueEntry, ChargingQueueSettings
from condocharge.models.tenancy import (
    AppUser,
    AppUserRole,
    Condominium,
    PushSubscription,
    ResidentNotificationHistory,
)


def _build_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)
    return testing_session_local


def _seed_condo(db: Session, *, name: str = "Push Condo") -> Condominium:
    condo = Condominium(name=name)
    db.add(condo)
    db.commit()
    db.refresh(condo)
    return condo


def _seed_user(
    db: Session,
    *,
    condo: Condominium,
    username: str,
    role: str,
) -> AppUser:
    user = AppUser(
        condominium_id=condo.id,
        username=username,
        password_hash=hash_password("password123"),
        role=role,
        is_active=1,
        email=f"{username}@example.com",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _seed_station(db: Session, *, condo: Condominium) -> ChargingStation:
    station = ChargingStation(condominium_id=condo.id, host="192.168.1.200", vendor="legrand_greenup", name="Garage A")
    db.add(station)
    db.commit()
    db.refresh(station)
    return station


def _seed_push_subscription(db: Session, *, user: AppUser, endpoint: str = "https://push.example/sub-1") -> PushSubscription:
    row = PushSubscription(
        user_id=user.id,
        endpoint=endpoint,
        p256dh="p256dh-key",
        auth="auth-key",
        active=1,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _seed_session(db: Session, *, condo: Condominium, resident: AppUser, station: ChargingStation) -> ChargingSession:
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
        source_key=f"session-{resident.id}",
        station_id=station.id,
        rfid_user_id=rfid.id,
        start_time=datetime.now(tz=UTC) - timedelta(hours=1),
        end_time=datetime.now(tz=UTC) - timedelta(minutes=5),
        energy_wh=6400,
        total_minutes=60,
        charging_minutes=55,
        idle_minutes=5,
        plug_type="Type2",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _build_client() -> tuple[TestClient, sessionmaker[Session]]:
    session_factory = _build_session_factory()
    with session_factory() as db:
        condo = _seed_condo(db)
        _seed_user(db, condo=condo, username="resident", role=AppUserRole.RESIDENT.value)
        _seed_user(db, condo=condo, username="admin", role=AppUserRole.ADMIN.value)

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    return TestClient(app), session_factory


def _auth_headers(client: TestClient, *, username: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "password123", "condominium": "Push Condo"},
    )
    assert response.status_code == 200
    token = response.json()["token"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


class SequenceOccupancyFetcher:
    def __init__(self, snapshots_by_call: list[Sequence[StationAvailabilitySnapshot]]) -> None:
        self._snapshots_by_call = snapshots_by_call
        self._index = 0

    def __call__(self, *, db: Session) -> Sequence[StationAvailabilitySnapshot]:
        del db
        value = self._snapshots_by_call[min(self._index, len(self._snapshots_by_call) - 1)]
        self._index += 1
        return value


def test_push_subscription_endpoints_update_profile_status() -> None:
    client, _ = _build_client()
    headers = _auth_headers(client, username="resident")
    payload = {
        "endpoint": "https://push.example/sub-1",
        "keys": {
            "p256dh": "p256dh-key",
            "auth": "auth-key",
        },
    }

    subscribe = client.post("/api/v1/push/subscribe", json=payload, headers=headers)
    assert subscribe.status_code == 200
    assert subscribe.json()["subscribed"] is True
    assert subscribe.json()["active_subscriptions"] == 1

    profile = client.get("/api/v1/resident/profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["push"]["subscribed"] is True
    assert profile.json()["push"]["active_subscriptions"] == 1

    unsubscribe = client.post("/api/v1/push/unsubscribe", json=payload, headers=headers)
    assert unsubscribe.status_code == 200
    assert unsubscribe.json()["subscribed"] is False
    assert unsubscribe.json()["active_subscriptions"] == 0


def test_push_service_creates_preview_history_for_charging_completed_without_vapid() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        settings = Settings(notifications_enabled=True, notification_recency_minutes=30)
        condo = _seed_condo(db)
        resident = _seed_user(db, condo=condo, username="resident", role=AppUserRole.RESIDENT.value)
        station = _seed_station(db, condo=condo)
        _seed_push_subscription(db, user=resident)
        session = _seed_session(db, condo=condo, resident=resident, station=station)
        service = PushNotificationService(db=db, settings=settings)

        created = service.send_charging_completed(session=session, resident=resident, station=station)

        history = db.scalars(select(ResidentNotificationHistory)).all()
        assert created == 1
        assert len(history) == 1
        assert history[0].channel == CHANNEL_WEB_PUSH
        assert history[0].notification_type == NOTIFICATION_TYPE_CHARGING_COMPLETED
        assert history[0].status == "preview"
    finally:
        db.close()


def test_push_station_poller_notifies_first_waiting_resident() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        now = datetime.now(tz=UTC)
        settings = Settings(
            notifications_enabled=True,
            queue_assignment_start_hour=0,
            queue_assignment_end_hour=24,
        )
        condo = _seed_condo(db)
        resident = _seed_user(db, condo=condo, username="resident", role=AppUserRole.RESIDENT.value)
        station = _seed_station(db, condo=condo)
        _seed_push_subscription(db, user=resident)
        db.add(ChargingQueueSettings(condominium_id=condo.id, queue_enabled=1))
        db.flush()
        db.add(
            ChargingQueueEntry(
                condominium_id=condo.id,
                resident_app_user_id=resident.id,
                status="waiting",
                joined_at=now - timedelta(minutes=2),
            )
        )
        db.commit()

        poller = PushStationNotificationPoller(
            db_factory=session_factory,
            settings=settings,
            occupancy_fetcher=SequenceOccupancyFetcher(
                [
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="charging",
                            observed_at=now - timedelta(minutes=1),
                        )
                    ]
                ]
            ),
        )

        created = poller.poll_once()

        history = db.scalars(
            select(ResidentNotificationHistory)
            .where(ResidentNotificationHistory.notification_type == NOTIFICATION_TYPE_QUEUE_NEXT_IN_LINE)
        ).all()
        assert created == 1
        assert len(history) == 1
        assert history[0].status == "preview"
    finally:
        db.close()


def test_push_station_available_notifies_only_first_in_queue() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        now = datetime.now(tz=UTC)
        settings = Settings(notifications_enabled=True)
        condo = _seed_condo(db)
        queued_resident = _seed_user(db, condo=condo, username="queued", role=AppUserRole.RESIDENT.value)
        non_queued_resident = _seed_user(db, condo=condo, username="nonqueued", role=AppUserRole.RESIDENT.value)
        station = _seed_station(db, condo=condo)
        _seed_push_subscription(db, user=queued_resident, endpoint="https://push.example/sub-queued")
        _seed_push_subscription(db, user=non_queued_resident, endpoint="https://push.example/sub-nonqueued")
        db.add(ChargingQueueSettings(condominium_id=condo.id, queue_enabled=1))
        db.flush()
        db.add(
            ChargingQueueEntry(
                condominium_id=condo.id,
                resident_app_user_id=queued_resident.id,
                status="waiting",
                joined_at=now - timedelta(minutes=2),
            )
        )
        db.commit()

        poller = PushStationNotificationPoller(
            db_factory=session_factory,
            settings=settings,
            occupancy_fetcher=SequenceOccupancyFetcher(
                [
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="charging",
                            observed_at=now - timedelta(minutes=1),
                        )
                    ],
                    [
                        StationAvailabilitySnapshot(
                            station_id=station.id,
                            condominium_id=condo.id,
                            computed_status="available",
                            observed_at=now,
                        )
                    ],
                ]
            ),
        )

        poller.poll_once()
        created = poller.poll_once()

        history = db.scalars(
            select(ResidentNotificationHistory)
            .where(ResidentNotificationHistory.notification_type == NOTIFICATION_TYPE_STATION_AVAILABLE)
            .order_by(ResidentNotificationHistory.id.asc())
        ).all()
        assert created == 1
        assert len(history) == 1
        assert history[0].resident_app_user_id == queued_resident.id
    finally:
        db.close()


def test_charging_completed_push_targets_only_session_resident() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        settings = Settings(notifications_enabled=True, notification_recency_minutes=30)
        condo = _seed_condo(db)
        resident_a = _seed_user(db, condo=condo, username="resident-a", role=AppUserRole.RESIDENT.value)
        resident_b = _seed_user(db, condo=condo, username="resident-b", role=AppUserRole.RESIDENT.value)
        station = _seed_station(db, condo=condo)
        _seed_push_subscription(db, user=resident_a, endpoint="https://push.example/sub-a")
        _seed_push_subscription(db, user=resident_b, endpoint="https://push.example/sub-b")
        session = _seed_session(db, condo=condo, resident=resident_a, station=station)
        service = PushNotificationService(db=db, settings=settings)

        created = service.send_charging_completed(session=session, resident=resident_a, station=station)

        history = db.scalars(
            select(ResidentNotificationHistory)
            .where(ResidentNotificationHistory.notification_type == NOTIFICATION_TYPE_CHARGING_COMPLETED)
            .order_by(ResidentNotificationHistory.id.asc())
        ).all()
        assert created == 1
        assert len(history) == 1
        assert history[0].resident_app_user_id == resident_a.id
    finally:
        db.close()


def test_push_agent_poller_notifies_admin_when_agent_goes_offline() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        now = datetime.now(tz=UTC)
        settings = Settings(notifications_enabled=True)
        condo = _seed_condo(db)
        admin = _seed_user(db, condo=condo, username="admin", role=AppUserRole.ADMIN.value)
        _seed_push_subscription(db, user=admin)
        db.add(
            AgentState(
                condominium_id=condo.id,
                agent_id="agent-1",
                last_heartbeat_at=now,
                last_station_update_at=now,
                last_session_import_at=now,
                heartbeat_count=1,
                polling_count=1,
                import_count=1,
                retry_count=0,
                failure_count=0,
            )
        )
        db.commit()

        poller = PushAgentStatusNotificationPoller(db_factory=session_factory, settings=settings)
        assert poller.poll_once(now=now) == 0

        created = poller.poll_once(now=now + timedelta(seconds=400))

        history = db.scalars(
            select(ResidentNotificationHistory)
            .where(ResidentNotificationHistory.channel == CHANNEL_WEB_PUSH)
            .order_by(ResidentNotificationHistory.id.asc())
        ).all()
        assert created == 1
        assert len(history) == 1
        assert history[0].status == "preview"
        assert history[0].resident_app_user_id == admin.id
    finally:
        db.close()
