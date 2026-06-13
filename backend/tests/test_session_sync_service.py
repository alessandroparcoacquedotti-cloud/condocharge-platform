from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.app.integrations.legrand.driver import ChargingSession as LegrandChargingSession
from condocharge.app.services.session_sync_service import SessionSyncService
from condocharge.db.base import Base
from condocharge.models.charging import ChargingSession, ChargingStation
from condocharge.models.tenancy import Condominium


class FakeDriver:
    def __init__(self, sessions_by_host: dict[str, list[LegrandChargingSession] | Exception]) -> None:
        self._sessions_by_host = sessions_by_host

    def login(self, host: str, username: str, password: str) -> None:
        return None

    def sync_charge_sessions(self, host: str) -> list[LegrandChargingSession]:
        value = self._sessions_by_host[host]
        if isinstance(value, Exception):
            raise value
        return value


def _build_db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal()


def test_sync_rolls_back_failed_host_and_continues_next_host() -> None:
    db = _build_db()
    try:
        condo = Condominium(name="Condo A")
        db.add(condo)
        db.flush()
        db.add_all(
            [
                ChargingStation(condominium_id=condo.id, host="192.168.1.200", vendor="legrand_greenup"),
                ChargingStation(condominium_id=condo.id, host="192.168.1.201", vendor="legrand_greenup"),
            ]
        )
        db.commit()

        driver = FakeDriver(
            {
                "192.168.1.200": RuntimeError("station offline"),
                "192.168.1.201": [
                    LegrandChargingSession(
                        start_time=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
                        end_time=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
                        energy_wh=5000,
                        total_minutes=60,
                        charging_minutes=55,
                        idle_minutes=5,
                        plug_type="Type2",
                        rfid_id="RFID-1",
                    )
                ],
            }
        )
        service = SessionSyncService(db=db, driver=driver)

        result = service.sync_hosts(
            condominium_id=condo.id,
            hosts=["192.168.1.200", "192.168.1.201"],
            username="user",
            password="pass",
        )

        assert len(result.errors) == 1
        assert "192.168.1.200" in result.errors[0]
        assert result.sessions_imported == 1
        assert result.total_sessions == 1

        stations = db.query(ChargingStation).order_by(ChargingStation.host.asc()).all()
        assert stations[0].host == "192.168.1.200"
        assert stations[0].status == "offline"
        assert stations[1].host == "192.168.1.201"
        assert stations[1].status == "online"
    finally:
        db.close()


def test_sync_duplicate_insert_fallback_keeps_host_progress() -> None:
    db = _build_db()
    try:
        condo = Condominium(name="Condo A")
        db.add(condo)
        db.flush()
        station = ChargingStation(condominium_id=condo.id, host="192.168.1.200", vendor="legrand_greenup")
        db.add(station)
        db.flush()
        existing = ChargingSession(
            condominium_id=condo.id,
            source_key="duplicate-source",
            station_id=station.id,
            rfid_user_id=None,
            start_time=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            energy_wh=5000,
            total_minutes=60,
            charging_minutes=55,
            idle_minutes=5,
            plug_type="Type2",
        )
        db.add(existing)
        db.commit()

        driver = FakeDriver(
            {
                "192.168.1.200": [
                    LegrandChargingSession(
                        start_time=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
                        end_time=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
                        energy_wh=5000,
                        total_minutes=60,
                        charging_minutes=55,
                        idle_minutes=5,
                        plug_type="Type2",
                    ),
                    LegrandChargingSession(
                        start_time=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
                        end_time=datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc),
                        energy_wh=4000,
                        total_minutes=60,
                        charging_minutes=50,
                        idle_minutes=10,
                        plug_type="Type2",
                    ),
                ]
            }
        )
        service = SessionSyncService(db=db, driver=driver)

        original_try_insert = service._try_insert_session
        calls = {"count": 0}

        def fake_try_insert(row: ChargingSession) -> bool:
            calls["count"] += 1
            if calls["count"] == 1:
                return False
            return original_try_insert(row)

        service._try_insert_session = fake_try_insert  # type: ignore[method-assign]
        service._find_existing_session = lambda **_: existing  # type: ignore[method-assign]

        result = service.sync_hosts(
            condominium_id=condo.id,
            hosts=["192.168.1.200"],
            username="user",
            password="pass",
        )

        assert result.errors == []
        assert result.sessions_imported == 1
        assert result.total_sessions == 2
        assert db.query(ChargingSession).count() == 2
    finally:
        db.close()
