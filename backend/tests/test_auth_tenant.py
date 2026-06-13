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


def _build_client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        condo_a = Condominium(name="Condo A")
        condo_b = Condominium(name="Condo B")
        db.add_all([condo_a, condo_b])
        db.flush()

        admin_a = AppUser(
            condominium_id=condo_a.id,
            username="admin_a",
            email="admin_a@example.com",
            password_hash=hash_password("password123"),
            role="admin",
            is_active=1,
        )
        viewer_a = AppUser(
            condominium_id=condo_a.id,
            username="viewer_a",
            password_hash=hash_password("password123"),
            role="viewer",
            is_active=1,
        )
        resident_real_a = AppUser(
            condominium_id=condo_a.id,
            username="resident_real",
            password_hash=hash_password("password123"),
            role="resident",
            is_active=1,
        )
        resident_forced_a = AppUser(
            condominium_id=condo_a.id,
            username="resident_forced",
            password_hash=hash_password("password123"),
            role="resident",
            is_active=1,
            must_change_password=1,
        )
        admin_b = AppUser(
            condominium_id=condo_b.id,
            username="admin_b",
            password_hash=hash_password("password123"),
            role="admin",
            is_active=1,
        )
        resident_real_b = AppUser(
            condominium_id=condo_b.id,
            username="resident_real",
            password_hash=hash_password("password123"),
            role="resident",
            is_active=1,
        )
        db.add_all([admin_a, viewer_a, resident_real_a, resident_forced_a, admin_b, resident_real_b])
        db.flush()

        station_a = ChargingStation(condominium_id=condo_a.id, host="192.168.1.200", vendor="legrand_greenup", name="A")
        station_b = ChargingStation(condominium_id=condo_b.id, host="10.0.0.5", vendor="legrand_greenup", name="B")
        rfid_a = RfidUser(condominium_id=condo_a.id, rfid_id="RFID-A", name="Alice")
        rfid_b = RfidUser(condominium_id=condo_b.id, rfid_id="RFID-B", name="Bob")
        db.add_all([station_a, station_b, rfid_a, rfid_b])
        db.flush()

        db.add_all(
            [
                ChargingSession(
                    condominium_id=condo_a.id,
                    source_key="a1",
                    station_id=station_a.id,
                    rfid_user_id=rfid_a.id,
                    start_time=datetime(2026, 6, 1, 8, 0, tzinfo=UTC),
                    end_time=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
                    energy_wh=5000,
                    total_minutes=60,
                    charging_minutes=55,
                    idle_minutes=5,
                    plug_type="Type2",
                ),
                ChargingSession(
                    condominium_id=condo_b.id,
                    source_key="b1",
                    station_id=station_b.id,
                    rfid_user_id=rfid_b.id,
                    start_time=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
                    end_time=datetime(2026, 6, 1, 11, 0, tzinfo=UTC),
                    energy_wh=8000,
                    total_minutes=60,
                    charging_minutes=60,
                    idle_minutes=0,
                    plug_type="Type2",
                ),
            ]
        )
        db.commit()

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    return TestClient(app)


def _login(client: TestClient, *, username: str, condominium: str | None = None) -> dict[str, str]:
    return _login_with_password(client, username=username, password="password123", condominium=condominium)


def _login_with_password(
    client: TestClient, *, username: str, password: str, condominium: str | None = None
) -> dict[str, str]:
    payload: dict[str, object] = {"username": username, "password": password}
    if condominium is not None:
        payload["condominium"] = condominium
    resp = client.post(
        "/api/v1/auth/login",
        json=payload,
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']['access_token']}"}


def test_login_admin_with_configured_condominium() -> None:
    client = _build_client()
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin_a", "password": "password123", "condominium": "Condo A"},
    )
    assert resp.status_code == 200


def test_login_resident_with_configured_condominium() -> None:
    client = _build_client()
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "resident_real", "password": "password123", "condominium": "Condo A"},
    )
    assert resp.status_code == 200


def test_login_accepts_trimmed_case_insensitive_condominium_name() -> None:
    client = _build_client()
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin_a", "password": "password123", "condominium": "  condo a  "},
    )
    assert resp.status_code == 200


def test_login_without_condominium_when_username_unique() -> None:
    client = _build_client()
    resp = client.post("/api/v1/auth/login", json={"username": "admin_a", "password": "password123"})
    assert resp.status_code == 200


def test_login_without_condominium_requires_selection_when_username_ambiguous() -> None:
    client = _build_client()
    resp = client.post("/api/v1/auth/login", json={"username": "resident_real", "password": "password123"})
    assert resp.status_code == 400


def test_login_invalid_credentials_returns_401() -> None:
    client = _build_client()
    resp = client.post("/api/v1/auth/login", json={"username": "admin_a", "password": "wrong-password"})
    assert resp.status_code == 401


def test_login_without_condominium_uses_unique_active_condominium() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        condo_a = Condominium(name="Condo A", is_active=1)
        condo_b = Condominium(name="Condo B", is_active=0)
        db.add_all([condo_a, condo_b])
        db.flush()

        db.add_all(
            [
                AppUser(
                    condominium_id=condo_a.id,
                    username="resident_real",
                    password_hash=hash_password("password123"),
                    role="resident",
                    is_active=1,
                ),
                AppUser(
                    condominium_id=condo_b.id,
                    username="resident_real",
                    password_hash=hash_password("password123"),
                    role="resident",
                    is_active=1,
                ),
            ]
        )
        db.commit()

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)
    resp = client.post("/api/v1/auth/login", json={"username": "resident_real", "password": "password123"})
    assert resp.status_code == 200


def test_auth_me_returns_condominium_and_role() -> None:
    client = _build_client()
    headers = _login(client, username="admin_a", condominium="Condo A")

    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["username"] == "admin_a"
    assert payload["email"] == "admin_a@example.com"
    assert payload["role"] == "admin"
    assert payload["condominium"]["name"] == "Condo A"


def test_tenant_isolation_scopes_sessions_and_dashboard() -> None:
    client = _build_client()
    headers_a = _login(client, username="admin_a", condominium="Condo A")
    headers_b = _login(client, username="admin_b", condominium="Condo B")

    sessions_a = client.get("/api/v1/sessions", params={"limit": 50, "offset": 0}, headers=headers_a).json()
    sessions_b = client.get("/api/v1/sessions", params={"limit": 50, "offset": 0}, headers=headers_b).json()
    assert sessions_a["pagination"]["total"] == 1
    assert sessions_a["items"][0]["source_key"] == "a1"
    assert sessions_b["pagination"]["total"] == 1
    assert sessions_b["items"][0]["source_key"] == "b1"

    dash_a = client.get("/api/v1/dashboard/summary", headers=headers_a).json()
    dash_b = client.get("/api/v1/dashboard/summary", headers=headers_b).json()
    assert dash_a["total_sessions"] == 1
    assert dash_a["total_energy_wh"] == 5000
    assert dash_b["total_sessions"] == 1
    assert dash_b["total_energy_wh"] == 8000


def test_viewer_cannot_access_admin_endpoints() -> None:
    client = _build_client()
    viewer_headers = _login(client, username="viewer_a", condominium="Condo A")
    admin_headers = _login(client, username="admin_a", condominium="Condo A")

    resp = client.get("/api/v1/admin/users", headers=viewer_headers)
    assert resp.status_code == 403

    resp2 = client.get("/api/v1/admin/users", headers=admin_headers)
    assert resp2.status_code == 200
    assert len(resp2.json()) >= 2


def test_resident_must_change_password_blocks_api_until_changed() -> None:
    client = _build_client()
    resident_headers = _login_with_password(
        client,
        username="resident_forced",
        password="password123",
        condominium="Condo A",
    )

    login_me = client.get("/api/v1/auth/me", headers=resident_headers)
    assert login_me.status_code == 200
    assert login_me.json()["must_change_password"] is True
    assert login_me.json()["last_login_at"] is not None

    blocked = client.get("/api/v1/resident/profile", headers=resident_headers)
    assert blocked.status_code == 428

    change_resp = client.post(
        "/api/v1/auth/change-password",
        headers=resident_headers,
        json={"current_password": "password123", "new_password": "newpassword123"},
    )
    assert change_resp.status_code == 200
    assert change_resp.json()["must_change_password"] is False

    allowed_headers = _login_with_password(
        client,
        username="resident_forced",
        password="newpassword123",
        condominium="Condo A",
    )
    allowed = client.get("/api/v1/resident/profile", headers=allowed_headers)
    assert allowed.status_code == 200
    assert allowed.json()["username"] == "resident_forced"
