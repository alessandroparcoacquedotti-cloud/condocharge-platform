from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.api.deps import get_db_session
from condocharge.core.security import hash_password
from condocharge.db.base import Base
from condocharge.main import create_app
from condocharge.models.charging import ChargingSession, ChargingStation
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
        db.add(admin)
        db.flush()

        s1 = ChargingStation(condominium_id=condo1.id, host="192.168.1.200", vendor="legrand_greenup", name="A")
        s2 = ChargingStation(condominium_id=condo2.id, host="192.168.1.201", vendor="legrand_greenup", name="B")
        db.add_all([s1, s2])
        db.commit()
        ids = {
            "condo1_id": condo1.id,
            "condo2_id": condo2.id,
            "admin_id": admin.id,
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


def _admin_auth_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "password123", "condominium": "Condo One"},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_agent_auth_rejects_missing_or_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, ids = _build_client(monkeypatch=monkeypatch)

    r1 = client.post("/api/v1/agent/heartbeat", json={"agent_version": "0.1", "hostname": "x", "started_at": "2026-06-18T08:00:00Z", "sent_at": "2026-06-18T08:01:00Z", "station_hosts": ["192.168.1.200"], "status_poll_interval_seconds": 30, "session_sync_interval_seconds": 300}, headers={"X-CondoCharge-Agent-Id": "test-agent", "X-CondoCharge-Condominium-Id": str(ids["condo1_id"])})
    assert r1.status_code == 401

    r2 = client.post(
        "/api/v1/agent/heartbeat",
        json={
            "agent_version": "0.1",
            "hostname": "x",
            "started_at": "2026-06-18T08:00:00Z",
            "sent_at": "2026-06-18T08:01:00Z",
            "station_hosts": ["192.168.1.200"],
            "status_poll_interval_seconds": 30,
            "session_sync_interval_seconds": 300,
        },
        headers=_agent_headers(condominium_id=ids["condo1_id"], token="wrong"),
    )
    assert r2.status_code == 401


def test_agent_auth_enforces_condominium_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, ids = _build_client(monkeypatch=monkeypatch)
    r = client.post(
        "/api/v1/agent/heartbeat",
        json={
            "agent_version": "0.1",
            "hostname": "x",
            "started_at": "2026-06-18T08:00:00Z",
            "sent_at": "2026-06-18T08:01:00Z",
            "station_hosts": ["192.168.1.200"],
            "status_poll_interval_seconds": 30,
            "session_sync_interval_seconds": 300,
        },
        headers=_agent_headers(condominium_id=ids["condo2_id"]),
    )
    assert r.status_code == 403


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
    assert items[0]["computed_status"] == "offline"
