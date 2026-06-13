from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.api.deps import get_db_session
from condocharge.core.security import hash_password
from condocharge.db.base import Base
from condocharge.main import create_app
from condocharge.models.charging import ChargingSession, ChargingStation, RfidUser
from condocharge.models.tenancy import AppUser, Condominium


def _seed_data(db: Session) -> dict[str, int]:
    condo = Condominium(name="Test Condo")
    db.add(condo)
    db.flush()

    app_user = AppUser(
        condominium_id=condo.id,
        username="testadmin",
        password_hash=hash_password("password123"),
        role="admin",
        is_active=1,
    )
    db.add(app_user)
    db.flush()

    station1 = ChargingStation(condominium_id=condo.id, host="192.168.1.200", vendor="legrand_greenup", name="Station A")
    station2 = ChargingStation(condominium_id=condo.id, host="192.168.1.201", vendor="legrand_greenup", name="Station B")
    user1 = RfidUser(condominium_id=condo.id, rfid_id="RFID-001", name="Alice")
    user2 = RfidUser(condominium_id=condo.id, rfid_id="RFID-002", name="Bob")
    db.add_all([station1, station2, user1, user2])
    db.flush()

    db.add_all(
        [
            ChargingSession(
                condominium_id=condo.id,
                source_key="s1",
                station_id=station1.id,
                rfid_user_id=user1.id,
                start_time=datetime(2026, 6, 1, 8, 0, tzinfo=UTC),
                end_time=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
                energy_wh=7000,
                total_minutes=60,
                charging_minutes=55,
                idle_minutes=5,
                plug_type="Type2",
            ),
            ChargingSession(
                condominium_id=condo.id,
                source_key="s2",
                station_id=station1.id,
                rfid_user_id=user2.id,
                start_time=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
                end_time=datetime(2026, 6, 2, 8, 30, tzinfo=UTC),
                energy_wh=3500,
                total_minutes=30,
                charging_minutes=28,
                idle_minutes=2,
                plug_type="Type2",
            ),
            ChargingSession(
                condominium_id=condo.id,
                source_key="s3",
                station_id=station2.id,
                rfid_user_id=user1.id,
                start_time=datetime(2026, 6, 3, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 6, 3, 11, 15, tzinfo=UTC),
                energy_wh=9000,
                total_minutes=75,
                charging_minutes=70,
                idle_minutes=5,
                plug_type="Type2",
            ),
        ]
    )
    db.commit()
    return {
        "condo_id": condo.id,
        "app_user_id": app_user.id,
        "station1_id": station1.id,
        "station2_id": station2.id,
        "user1_id": user1.id,
        "user2_id": user2.id,
    }


def _build_client() -> tuple[TestClient, dict[str, int]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        ids = _seed_data(db)

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)
    return client, ids


def _auth_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "testadmin", "password": "password123", "condominium": "Test Condo"},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_stations_endpoints_support_pagination_and_detail() -> None:
    client, ids = _build_client()
    headers = _auth_headers(client)

    response = client.get("/api/v1/stations", params={"limit": 1, "offset": 0}, headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"] == {"total": 2, "limit": 1, "offset": 0}
    assert len(payload["items"]) == 1
    assert payload["items"][0]["session_count"] == 2
    assert payload["items"][0]["total_energy_wh"] == 10500

    detail = client.get(f"/api/v1/stations/{ids['station1_id']}", headers=headers)
    assert detail.status_code == 200
    item = detail.json()
    assert item["id"] == ids["station1_id"]
    assert item["host"] == "192.168.1.200"
    assert item["latest_session"]["source_key"] == "s2"


def test_sessions_endpoint_supports_filters() -> None:
    client, ids = _build_client()
    headers = _auth_headers(client)

    response = client.get(
        "/api/v1/sessions",
        params={
            "station_id": ids["station1_id"],
            "rfid_id": "RFID-002",
            "start_date": "2026-06-02T00:00:00Z",
            "end_date": "2026-06-02T23:59:59Z",
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"]["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["source_key"] == "s2"
    assert payload["items"][0]["station"]["id"] == ids["station1_id"]
    assert payload["items"][0]["rfid_user"]["rfid_id"] == "RFID-002"

    detail = client.get("/api/v1/sessions/3", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["source_key"] == "s3"


def test_users_endpoints_return_aggregates() -> None:
    client, ids = _build_client()
    headers = _auth_headers(client)

    response = client.get("/api/v1/users", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"]["total"] == 2
    assert payload["items"][0]["rfid_id"] == "RFID-001"
    assert payload["items"][0]["total_energy_wh"] == 16000

    detail = client.get(f"/api/v1/users/{ids['user1_id']}", headers=headers)
    assert detail.status_code == 200
    item = detail.json()
    assert item["session_count"] == 2
    assert item["latest_session"]["source_key"] == "s3"


def test_dashboard_summary_returns_expected_metrics() -> None:
    client, _ = _build_client()
    headers = _auth_headers(client)

    response = client.get("/api/v1/dashboard/summary", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_sessions"] == 3
    assert payload["total_energy_wh"] == 19500
    assert payload["total_energy_kwh"] == 19.5
    assert payload["total_users"] == 2
    assert payload["total_stations"] == 2
    assert payload["latest_session"]["source_key"] == "s3"
    assert payload["top_users_by_energy"][0]["rfid_id"] == "RFID-001"
    assert payload["top_users_by_energy"][0]["total_energy_wh"] == 16000


def test_openapi_includes_v1_routes() -> None:
    client, _ = _build_client()

    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/stations" in paths
    assert "/api/v1/sessions" in paths
    assert "/api/v1/users" in paths
    assert "/api/v1/dashboard/summary" in paths
