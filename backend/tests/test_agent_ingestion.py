from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
import os
import tempfile
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.api.deps import get_db_session
from condocharge.api.v1 import resident as resident_api
from condocharge.api.v1 import stations as stations_api
from condocharge.app.services.station_status_history_service import record_station_status_transition
import condocharge.app.services.station_status_history_service as history_service
from condocharge.core.security import hash_password
from condocharge.db.base import Base
from condocharge.main import create_app
from condocharge.models.charging import AgentState, ChargingSession, ChargingStation, StationStatusHistory
from condocharge.models.tenancy import AppUser, Condominium


def _build_client(*, monkeypatch: pytest.MonkeyPatch, occupancy_source: str = "live") -> tuple[TestClient, sessionmaker[Session], dict[str, int]]:
    monkeypatch.setenv("CONDOCHARGE_AGENT_ENABLED", "true")
    monkeypatch.setenv("CONDOCHARGE_AGENT_TOKEN_CURRENT", "test-agent-token")
    monkeypatch.setenv("CONDOCHARGE_AGENT_ALLOWED_CONDOMINIUM_IDS", "1")
    monkeypatch.setenv("CONDOCHARGE_AGENT_OCCUPANCY_SOURCE", occupancy_source)
    monkeypatch.setenv("CONDOCHARGE_AGENT_STALE_AFTER_SECONDS", "90")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        condo1 = Condominium(name="Condo One")
        condo2 = Condominium(name="Condo Two")
        db.add_all([condo1, condo2])
        db.flush()

        admin = AppUser(
            condominium_id=condo1.id,
            username="admin",
            password_hash=hash_password("password123"),
            role="admin",
            is_active=1,
        )
        resident = AppUser(
            condominium_id=condo1.id,
            username="resident",
            password_hash=hash_password("password123"),
            role="resident",
            is_active=1,
        )
        db.add_all([admin, resident])
        db.flush()

        s1 = ChargingStation(condominium_id=condo1.id, host="192.168.1.200", vendor="legrand_greenup", name="A")
        s2 = ChargingStation(condominium_id=condo2.id, host="192.168.1.201", vendor="legrand_greenup", name="B")
        db.add_all([s1, s2])
        db.commit()
        ids = {
            "condo1_id": condo1.id,
            "condo2_id": condo2.id,
            "admin_id": admin.id,
            "resident_id": resident.id,
            "station1_id": s1.id,
            "station2_id": s2.id,
        }

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    return TestClient(app), TestingSessionLocal, ids


def _agent_headers(*, condominium_id: int, token: str = "test-agent-token") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-CondoCharge-Agent-Id": "test-agent",
        "X-CondoCharge-Condominium-Id": str(condominium_id),
    }


def _heartbeat_body() -> dict[str, object]:
    return {
        "agent_version": "0.1",
        "hostname": "mini-pc-agent",
        "started_at": "2026-06-18T08:00:00Z",
        "sent_at": "2026-06-18T08:01:00Z",
        "station_hosts": ["192.168.1.200"],
        "heartbeat_interval_seconds": 60,
        "status_poll_interval_seconds": 30,
        "session_sync_interval_seconds": 300,
        "heartbeat_count": 12,
        "polling_count": 24,
        "import_count": 3,
        "retry_count": 4,
        "failure_count": 1,
    }


def _admin_auth_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "password123", "condominium": "Condo One"},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _resident_auth_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "resident", "password": "password123", "condominium": "Condo One"},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_agent_auth_rejects_missing_or_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, ids = _build_client(monkeypatch=monkeypatch)

    r1 = client.post("/api/v1/agent/heartbeat", json=_heartbeat_body(), headers={"X-CondoCharge-Agent-Id": "test-agent", "X-CondoCharge-Condominium-Id": str(ids["condo1_id"])})
    assert r1.status_code == 401

    r2 = client.post(
        "/api/v1/agent/heartbeat",
        json=_heartbeat_body(),
        headers=_agent_headers(condominium_id=ids["condo1_id"], token="wrong"),
    )
    assert r2.status_code == 401


def test_agent_auth_enforces_condominium_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, ids = _build_client(monkeypatch=monkeypatch)
    r = client.post(
        "/api/v1/agent/heartbeat",
        json=_heartbeat_body(),
        headers=_agent_headers(condominium_id=ids["condo2_id"]),
    )
    assert r.status_code == 403


def test_heartbeat_persists_latest_agent_state(monkeypatch: pytest.MonkeyPatch) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch)

    resp = client.post(
        "/api/v1/agent/heartbeat",
        json=_heartbeat_body(),
        headers=_agent_headers(condominium_id=ids["condo1_id"]),
    )

    assert resp.status_code == 200
    with TestingSessionLocal() as db:
        state = db.scalar(select(AgentState).where(AgentState.condominium_id == ids["condo1_id"]))
        assert state is not None
        assert state.agent_id == "test-agent"
        assert state.hostname == "mini-pc-agent"
        assert state.heartbeat_count == 12
        assert state.polling_count == 24
        assert state.import_count == 3
        assert state.retry_count == 4
        assert state.failure_count == 1
        assert state.last_heartbeat_at is not None


def test_status_ingestion_updates_station_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch)
    resp = client.post(
        "/api/v1/agent/stations/status/batch",
        json={
            "sent_at": "2026-06-18T08:37:10Z",
            "stations": [
                {
                    "host": "192.168.1.200",
                    "observed_at": "2026-06-18T08:37:07Z",
                    "reachable": True,
                    "connector_status": "available",
                    "rfid_enabled": True,
                    "charging_state": "ready",
                    "last_error": None,
                    "last_status_payload": {"state_text": "Connected"},
                }
            ],
        },
        headers=_agent_headers(condominium_id=ids["condo1_id"]),
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["updated"] == 1
    assert payload["rejected"] == 0

    with TestingSessionLocal() as db:
        station = db.get(ChargingStation, ids["station1_id"])
        assert station is not None
        assert station.status_source == "agent"
        assert station.status == "available"
        assert station.last_poll_at is not None
        assert station.last_seen_at is not None
        assert station.connector_status == "available"
        assert station.rfid_enabled is True
        assert station.charging_state == "ready"
        assert station.last_status_payload_json is not None


def test_status_ingestion_creates_transition_on_status_change(monkeypatch: pytest.MonkeyPatch) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch)
    resp = client.post(
        "/api/v1/agent/stations/status/batch",
        json={
            "sent_at": "2026-06-18T08:37:10Z",
            "stations": [
                {
                    "host": "192.168.1.200",
                    "observed_at": "2026-06-18T08:37:07Z",
                    "reachable": True,
                    "connector_status": "available",
                    "rfid_enabled": True,
                    "charging_state": "ready",
                    "last_error": None,
                    "last_status_payload": {"state_text": "Connected"},
                }
            ],
        },
        headers=_agent_headers(condominium_id=ids["condo1_id"]),
    )
    assert resp.status_code == 200

    with TestingSessionLocal() as db:
        rows = db.scalars(select(StationStatusHistory).order_by(StationStatusHistory.id.asc())).all()
        assert len(rows) == 1
        assert rows[0].station_id == ids["station1_id"]
        assert rows[0].host == "192.168.1.200"
        assert rows[0].previous_status == "unknown"
        assert rows[0].new_status == "free"
        assert rows[0].source == "agent"


def test_status_ingestion_does_not_create_transition_when_status_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch)
    body = {
        "sent_at": "2026-06-18T08:37:10Z",
        "stations": [
            {
                "host": "192.168.1.200",
                "observed_at": "2026-06-18T08:37:07Z",
                "reachable": True,
                "connector_status": "available",
                "rfid_enabled": True,
                "charging_state": "ready",
                "last_error": None,
                "last_status_payload": {"state_text": "Connected"},
            }
        ],
    }
    first = client.post(
        "/api/v1/agent/stations/status/batch",
        json=body,
        headers=_agent_headers(condominium_id=ids["condo1_id"]),
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/agent/stations/status/batch",
        json=body,
        headers=_agent_headers(condominium_id=ids["condo1_id"]),
    )
    assert second.status_code == 200

    with TestingSessionLocal() as db:
        rows = db.scalars(select(StationStatusHistory).order_by(StationStatusHistory.id.asc())).all()
        assert len(rows) == 1


def test_mixed_source_transitions_use_latest_history_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch)
    del client

    with TestingSessionLocal() as db:
        station = db.get(ChargingStation, ids["station1_id"])
        assert station is not None
        record_station_status_transition(
            db=db,
            station=station,
            new_status="free",
            source="agent",
            created_at=datetime(2026, 6, 18, 8, 0, tzinfo=UTC),
        )
        db.commit()

    with TestingSessionLocal() as db:
        station = db.get(ChargingStation, ids["station1_id"])
        assert station is not None
        station.status = "charging"
        station.connector_status = "charging"
        station.status_source = "agent"
        db.commit()

    with TestingSessionLocal() as db:
        station = db.get(ChargingStation, ids["station1_id"])
        assert station is not None
        record_station_status_transition(
            db=db,
            station=station,
            new_status="free",
            source="live_poll",
        )
        db.commit()

    with TestingSessionLocal() as db:
        station = db.get(ChargingStation, ids["station1_id"])
        assert station is not None
        record_station_status_transition(
            db=db,
            station=station,
            new_status="unavailable",
            source="telegram_status",
        )
        db.commit()

    with TestingSessionLocal() as db:
        station = db.get(ChargingStation, ids["station1_id"])
        assert station is not None
        station.status = "available"
        station.connector_status = "available"
        station.status_source = "agent"
        db.commit()

    with TestingSessionLocal() as db:
        rows = db.scalars(
            select(StationStatusHistory)
            .where(StationStatusHistory.station_id == ids["station1_id"])
            .order_by(StationStatusHistory.id.asc())
        ).all()
        pairs = [(row.previous_status, row.new_status, row.source) for row in rows[1:]]
        assert pairs == [
            ("free", "busy", "agent"),
            ("busy", "free", "live_poll"),
            ("free", "unavailable", "telegram_status"),
            ("unavailable", "free", "agent"),
        ]


def test_concurrent_writers_do_not_create_duplicate_transition_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONDOCHARGE_AGENT_ENABLED", "true")
    fd, db_path = tempfile.mkstemp(prefix="station-history-concurrency-", suffix=".sqlite3")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)

    try:
        with TestingSessionLocal() as db:
            condo = Condominium(name="Concurrency Condo")
            db.add(condo)
            db.flush()
            db.add(
                AppUser(
                    condominium_id=condo.id,
                    username="resident",
                    password_hash=hash_password("password123"),
                    role="resident",
                    is_active=1,
                )
            )
            station = ChargingStation(
                condominium_id=condo.id,
                host="192.168.1.200",
                vendor="legrand_greenup",
                name="A",
                status="available",
                status_source="agent",
                connector_status="available",
            )
            db.add(station)
            db.commit()
            station_id = station.id

        original_latest = history_service._latest_history_row
        barrier = threading.Barrier(2)
        errors: list[str] = []

        def patched_latest(*, db: Session, station_id: int):
            row = original_latest(db=db, station_id=station_id)
            barrier.wait(timeout=5)
            return row

        history_service._latest_history_row = patched_latest

        def agent_worker() -> None:
            try:
                with TestingSessionLocal() as db:
                    station = db.get(ChargingStation, station_id)
                    assert station is not None
                    station.status = "charging"
                    station.connector_status = "charging"
                    station.status_source = "agent"
                    db.commit()
            except Exception as exc:  # pragma: no cover - assertion aid
                errors.append(f"agent:{exc!r}")

        def telegram_worker() -> None:
            try:
                with TestingSessionLocal() as db:
                    station = db.get(ChargingStation, station_id)
                    assert station is not None
                    record_station_status_transition(
                        db=db,
                        station=station,
                        new_status="busy",
                        source="telegram_status",
                    )
                    db.commit()
            except Exception as exc:  # pragma: no cover - assertion aid
                errors.append(f"telegram:{exc!r}")

        threads = [threading.Thread(target=agent_worker), threading.Thread(target=telegram_worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
    finally:
        history_service._latest_history_row = original_latest
        with TestingSessionLocal() as db:
            rows = db.scalars(select(StationStatusHistory).order_by(StationStatusHistory.id.asc())).all()
            assert len(rows) == 1
            assert rows[0].previous_status == "free"
            assert rows[0].new_status == "busy"
        assert errors == []
        engine.dispose()
        os.remove(db_path)


def test_status_ingestion_rejects_cross_tenant_host(monkeypatch: pytest.MonkeyPatch) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch)
    resp = client.post(
        "/api/v1/agent/stations/status/batch",
        json={
            "sent_at": "2026-06-18T08:37:10Z",
            "stations": [
                {
                    "host": "192.168.1.201",
                    "observed_at": "2026-06-18T08:37:07Z",
                    "reachable": True,
                    "connector_status": "available",
                    "rfid_enabled": True,
                    "charging_state": "ready",
                    "last_error": None,
                    "last_status_payload": {"state_text": "Connected"},
                }
            ],
        },
        headers=_agent_headers(condominium_id=ids["condo1_id"]),
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 0
    assert resp.json()["rejected"] == 1

    with TestingSessionLocal() as db:
        station2 = db.get(ChargingStation, ids["station2_id"])
        assert station2 is not None
        assert station2.status_source != "agent"


def test_session_ingestion_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch)
    body = {
        "sent_at": "2026-06-18T08:40:00Z",
        "hosts": [
            {
                "host": "192.168.1.200",
                "sessions": [
                    {
                        "start_time": "2026-06-18T06:20:00Z",
                        "end_time": "2026-06-18T07:10:00Z",
                        "energy_wh": 5400,
                        "total_minutes": 50,
                        "charging_minutes": 42,
                        "idle_minutes": 8,
                        "plug_type": "T2",
                        "rfid_id": "ABC123",
                        "rfid_name": "Mario",
                    }
                ],
            }
        ],
    }
    r1 = client.post("/api/v1/agent/sessions/import", json=body, headers=_agent_headers(condominium_id=ids["condo1_id"]))
    assert r1.status_code == 200
    assert r1.json()["sessions_imported"] == 1

    r2 = client.post("/api/v1/agent/sessions/import", json=body, headers=_agent_headers(condominium_id=ids["condo1_id"]))
    assert r2.status_code == 200
    assert r2.json()["sessions_imported"] == 0
    assert r2.json()["duplicates_ignored"] == 1

    with TestingSessionLocal() as db:
        count = int(db.scalar(select(func.count()).select_from(ChargingSession)) or 0)
        assert count == 1
        station = db.get(ChargingStation, ids["station1_id"])
        assert station is not None
        assert station.last_sync_at is not None


def test_session_ingestion_rejects_cross_tenant_host(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, ids = _build_client(monkeypatch=monkeypatch)
    r = client.post(
        "/api/v1/agent/sessions/import",
        json={
            "sent_at": "2026-06-18T08:40:00Z",
            "hosts": [{"host": "192.168.1.201", "sessions": []}],
        },
        headers=_agent_headers(condominium_id=ids["condo1_id"]),
    )
    assert r.status_code == 409


def test_db_backed_occupancy_marks_stale_as_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch, occupancy_source="db")
    now = datetime.now(tz=UTC)

    with TestingSessionLocal() as db:
        station = db.get(ChargingStation, ids["station1_id"])
        assert station is not None
        station.status = "available"
        station.status_source = "agent"
        station.last_poll_at = now - timedelta(seconds=120)
        station.connector_status = "available"
        db.commit()

    headers = _admin_auth_headers(client)
    resp = client.get("/api/v1/stations/occupancy", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["computed_status"] == "unavailable"
    assert items[0]["source"] == "db"


def test_fresh_agent_status_available_is_authoritative_over_live_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch, occupancy_source="live")
    now = datetime.now(tz=UTC)

    with TestingSessionLocal() as db:
        station = db.get(ChargingStation, ids["station1_id"])
        assert station is not None
        station.status = "available"
        station.status_source = "agent"
        station.last_seen_at = now
        station.last_poll_at = now
        station.connector_status = "available"
        station.charging_state = "ready"
        db.commit()

    monkeypatch.setattr(stations_api, "_resolve_legrand_credentials", lambda: None)
    monkeypatch.setattr(resident_api, "_resolve_legrand_credentials", lambda: None)
    admin_headers = _admin_auth_headers(client)
    resident_headers = _resident_auth_headers(client)

    admin_resp = client.get("/api/v1/stations/occupancy", headers=admin_headers)
    assert admin_resp.status_code == 200
    admin_item = admin_resp.json()["items"][0]
    assert admin_item["computed_status"] == "free"
    assert admin_item["source"] == "agent"

    resident_resp = client.get("/api/v1/resident/stations/occupancy", headers=resident_headers)
    assert resident_resp.status_code == 200
    resident_item = resident_resp.json()["items"][0]
    assert resident_item["computed_status"] == "free"
    assert resident_item["source"] == "agent"


def test_fresh_agent_status_busy_is_authoritative(monkeypatch: pytest.MonkeyPatch) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch, occupancy_source="live")
    now = datetime.now(tz=UTC)

    with TestingSessionLocal() as db:
        station = db.get(ChargingStation, ids["station1_id"])
        assert station is not None
        station.status = "charging"
        station.status_source = "agent"
        station.last_seen_at = now
        station.last_poll_at = now
        station.connector_status = "charging"
        station.charging_state = "charging"
        db.commit()

    monkeypatch.setattr(stations_api, "_resolve_legrand_credentials", lambda: None)
    monkeypatch.setattr(resident_api, "_resolve_legrand_credentials", lambda: None)
    admin_headers = _admin_auth_headers(client)

    admin_resp = client.get("/api/v1/stations/occupancy", headers=admin_headers)
    assert admin_resp.status_code == 200
    admin_item = admin_resp.json()["items"][0]
    assert admin_item["computed_status"] == "busy"
    assert admin_item["source"] == "agent"


def test_stale_agent_status_falls_back_to_live_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch, occupancy_source="live")
    now = datetime.now(tz=UTC)

    with TestingSessionLocal() as db:
        station = db.get(ChargingStation, ids["station1_id"])
        assert station is not None
        station.status = "available"
        station.status_source = "agent"
        station.last_seen_at = now - timedelta(seconds=150)
        station.last_poll_at = now - timedelta(seconds=150)
        station.connector_status = "available"
        db.commit()

    stations_api._live_driver_hosts.clear()
    monkeypatch.setattr(stations_api, "_resolve_legrand_credentials", lambda: ("user", "password"))
    monkeypatch.setattr(resident_api, "_resolve_legrand_credentials", lambda: ("user", "password"))
    monkeypatch.setattr(stations_api._live_driver, "login", lambda host, username, password: None)

    class _FaultedStatus:
        connector_status = stations_api.ConnectorStatus.FAULTED

    monkeypatch.setattr(stations_api._live_driver, "get_station_status", lambda host: _FaultedStatus())
    admin_headers = _admin_auth_headers(client)
    resident_headers = _resident_auth_headers(client)

    admin_resp = client.get("/api/v1/stations/occupancy", headers=admin_headers)
    assert admin_resp.status_code == 200
    admin_item = admin_resp.json()["items"][0]
    assert admin_item["computed_status"] == "unavailable"
    assert admin_item["source"] == "live"

    resident_resp = client.get("/api/v1/resident/stations/occupancy", headers=resident_headers)
    assert resident_resp.status_code == 200
    resident_item = resident_resp.json()["items"][0]
    assert resident_item["computed_status"] == "unavailable"
    assert resident_item["source"] == "live"


def test_dashboard_agent_status_endpoint_returns_green_yellow_and_red(monkeypatch: pytest.MonkeyPatch) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch)
    headers = _admin_auth_headers(client)
    now = datetime.now(tz=UTC)

    with TestingSessionLocal() as db:
        state = AgentState(
            condominium_id=ids["condo1_id"],
            agent_id="test-agent",
            last_heartbeat_at=now - timedelta(seconds=30),
            last_station_update_at=now - timedelta(seconds=20),
            last_session_import_at=now - timedelta(minutes=2),
            heartbeat_count=10,
            polling_count=20,
            import_count=3,
            retry_count=1,
            failure_count=0,
        )
        db.add(state)
        db.commit()

    green = client.get("/api/v1/dashboard/agent-status", headers=headers)
    assert green.status_code == 200
    assert green.json()["health_color"] == "green"
    assert green.json()["online"] is True

    with TestingSessionLocal() as db:
        state = db.scalar(select(AgentState).where(AgentState.condominium_id == ids["condo1_id"]))
        assert state is not None
        state.last_heartbeat_at = now - timedelta(seconds=120)
        db.commit()

    yellow = client.get("/api/v1/dashboard/agent-status", headers=headers)
    assert yellow.status_code == 200
    assert yellow.json()["health_color"] == "yellow"
    assert yellow.json()["online"] is True

    with TestingSessionLocal() as db:
        state = db.scalar(select(AgentState).where(AgentState.condominium_id == ids["condo1_id"]))
        assert state is not None
        state.last_heartbeat_at = now - timedelta(seconds=240)
        db.commit()

    red = client.get("/api/v1/dashboard/agent-status", headers=headers)
    assert red.status_code == 200
    assert red.json()["health_color"] == "red"
    assert red.json()["online"] is False


def test_dashboard_summary_includes_persisted_agent_status(monkeypatch: pytest.MonkeyPatch) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch)
    headers = _admin_auth_headers(client)

    with TestingSessionLocal() as db:
        db.add(
            AgentState(
                condominium_id=ids["condo1_id"],
                agent_id="test-agent",
                last_heartbeat_at=datetime.now(tz=UTC),
                last_station_update_at=datetime.now(tz=UTC),
                last_session_import_at=datetime.now(tz=UTC),
                heartbeat_count=7,
                polling_count=11,
                import_count=2,
                retry_count=5,
                failure_count=1,
            )
        )
        db.commit()

    resp = client.get("/api/v1/dashboard/summary", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["agent_status"]["agent_id"] == "test-agent"
    assert payload["agent_status"]["heartbeat_count"] == 7
    assert payload["agent_status"]["retry_count"] == 5


@pytest.mark.parametrize(
    ("connector_status", "station_status", "expected"),
    [
        ("available", "available", "free"),
        ("charging", "charging", "busy"),
        ("occupied", "occupied", "busy"),
        ("faulted", "faulted", "unavailable"),
        ("unknown", "unknown", "unavailable"),
        (None, "unreachable", "unavailable"),
        (None, "degraded", "unavailable"),
    ],
)
def test_db_backed_occupancy_maps_all_hardened_states(
    monkeypatch: pytest.MonkeyPatch,
    connector_status: str | None,
    station_status: str,
    expected: str,
) -> None:
    client, TestingSessionLocal, ids = _build_client(monkeypatch=monkeypatch, occupancy_source="db")
    admin_headers = _admin_auth_headers(client)
    resident_headers = _resident_auth_headers(client)
    now = datetime.now(tz=UTC)

    with TestingSessionLocal() as db:
        station = db.get(ChargingStation, ids["station1_id"])
        assert station is not None
        station.status = station_status
        station.status_source = "agent"
        station.last_poll_at = now
        station.connector_status = connector_status
        db.commit()

    admin_resp = client.get("/api/v1/stations/occupancy", headers=admin_headers)
    assert admin_resp.status_code == 200
    assert admin_resp.json()["items"][0]["computed_status"] == expected
    assert admin_resp.json()["items"][0]["source"] == "agent"

    resident_resp = client.get("/api/v1/resident/stations/occupancy", headers=resident_headers)
    assert resident_resp.status_code == 200
    assert resident_resp.json()["items"][0]["computed_status"] == expected
    assert resident_resp.json()["items"][0]["source"] == "agent"


@pytest.mark.parametrize(
    ("connector", "expected"),
    [
        (stations_api.ConnectorStatus.AVAILABLE, "free"),
        (stations_api.ConnectorStatus.CHARGING, "busy"),
        (stations_api.ConnectorStatus.OCCUPIED, "busy"),
        (stations_api.ConnectorStatus.FAULTED, "unavailable"),
        (stations_api.ConnectorStatus.UNKNOWN, "unavailable"),
    ],
)
def test_live_occupancy_snapshot_maps_connector_states(
    monkeypatch: pytest.MonkeyPatch,
    connector: object,
    expected: str,
) -> None:
    station = ChargingStation(id=1, condominium_id=1, host="192.168.1.200", vendor="legrand_greenup", name="A")
    stations_api._live_driver_hosts.clear()

    class _FakeStatus:
        def __init__(self, connector_status: object) -> None:
            self.connector_status = connector_status

    monkeypatch.setattr(stations_api._live_driver, "login", lambda host, username, password: None)
    monkeypatch.setattr(stations_api._live_driver, "get_station_status", lambda host: _FakeStatus(connector))

    result = stations_api._station_occupancy_snapshot(
        station=station,
        credentials=("user", "password"),
    )

    assert result.computed_status == expected
    assert result.source == "live"


def test_live_occupancy_snapshot_maps_occupied_connector_to_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    station = ChargingStation(id=1, condominium_id=1, host="192.168.1.200", vendor="legrand_greenup", name="A")
    stations_api._live_driver_hosts.clear()

    class _FakeStatus:
        connector_status = stations_api.ConnectorStatus.OCCUPIED

    monkeypatch.setattr(stations_api._live_driver, "login", lambda host, username, password: None)
    monkeypatch.setattr(stations_api._live_driver, "get_station_status", lambda host: _FakeStatus())

    result = stations_api._station_occupancy_snapshot(
        station=station,
        credentials=("user", "password"),
    )

    assert result.connector_status == "occupied"
    assert result.computed_status == "busy"
    assert result.unavailable_reason is None
    assert result.source == "live"


def test_live_occupancy_snapshot_maps_unreachable_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    station = ChargingStation(id=1, condominium_id=1, host="192.168.1.200", vendor="legrand_greenup", name="A")
    stations_api._live_driver_hosts.clear()

    monkeypatch.setattr(stations_api._live_driver, "login", lambda host, username, password: None)

    def _raise(host: str) -> object:
        raise RuntimeError("network down")

    monkeypatch.setattr(stations_api._live_driver, "get_station_status", _raise)

    result = stations_api._station_occupancy_snapshot(
        station=station,
        credentials=("user", "password"),
    )

    assert result.computed_status == "unavailable"
    assert result.source == "live"
