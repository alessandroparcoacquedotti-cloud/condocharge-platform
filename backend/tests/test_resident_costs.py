from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.api.deps import get_db_session
from condocharge.app.services.email_service import EmailService
from condocharge.core.config import get_settings
from condocharge.core.security import hash_password
from condocharge.db.base import Base
from condocharge.main import create_app
from condocharge.models.charging import ChargingSession, ChargingStation, RfidUser
from condocharge.models.tenancy import AppUser, Condominium


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _build_client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        condo = Condominium(name="Condo", energy_price_eur_per_kwh=0.30)
        other_condo = Condominium(name="Other Condo", energy_price_eur_per_kwh=0.45)
        db.add_all([condo, other_condo])
        db.flush()

        admin = AppUser(
            condominium_id=condo.id,
            username="admin",
            password_hash=hash_password("password123"),
            role="admin",
            is_active=1,
        )
        res1 = AppUser(
            condominium_id=condo.id,
            username="resident1",
            password_hash=hash_password("password123"),
            role="resident",
            is_active=1,
        )
        res2 = AppUser(
            condominium_id=condo.id,
            username="resident2",
            password_hash=hash_password("password123"),
            role="resident",
            is_active=1,
        )
        db.add_all([admin, res1, res2])
        db.flush()

        other_admin = AppUser(
            condominium_id=other_condo.id,
            username="other_admin",
            password_hash=hash_password("password123"),
            role="admin",
            is_active=1,
        )
        db.add(other_admin)
        db.flush()

        station = ChargingStation(condominium_id=condo.id, host="192.168.1.200", vendor="legrand_greenup", name="S1")
        other_station = ChargingStation(
            condominium_id=other_condo.id,
            host="10.10.10.10",
            vendor="legrand_greenup",
            name="S2",
        )
        db.add_all([station, other_station])
        db.flush()

        card1 = RfidUser(condominium_id=condo.id, app_user_id=res1.id, rfid_id="RFID-1", name="Card1")
        card2 = RfidUser(condominium_id=condo.id, app_user_id=res2.id, rfid_id="RFID-2", name="Card2")
        other_card = RfidUser(condominium_id=other_condo.id, rfid_id="RFID-OTHER", name="OtherCard")
        db.add_all([card1, card2, other_card])
        db.flush()

        db.add_all(
            [
                ChargingSession(
                    condominium_id=condo.id,
                    source_key="s1",
                    station_id=station.id,
                    rfid_user_id=card1.id,
                    start_time=datetime(2026, 6, 1, 8, 0, tzinfo=UTC),
                    end_time=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
                    energy_wh=10000,
                    total_minutes=60,
                    charging_minutes=55,
                    idle_minutes=5,
                    plug_type="Type2",
                ),
                ChargingSession(
                    condominium_id=condo.id,
                    source_key="s2",
                    station_id=station.id,
                    rfid_user_id=card2.id,
                    start_time=datetime(2026, 6, 10, 8, 0, tzinfo=UTC),
                    end_time=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
                    energy_wh=5000,
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


def _login(client: TestClient, *, username: str, condominium: str = "Condo") -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "password123", "condominium": condominium},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _enable_invitation_email(monkeypatch, sent_messages: list[dict[str, str]]) -> None:
    monkeypatch.setenv("CONDOCHARGE_ENV", "pilot")
    monkeypatch.setenv("CONDOCHARGE_JWT_SECRET_KEY", "this-is-a-safe-pilot-secret-1234567890")
    monkeypatch.setenv("CONDOCHARGE_EMAIL_ENABLED", "true")
    monkeypatch.setenv("CONDOCHARGE_PUBLIC_URL", "https://condocharge.example")
    get_settings.cache_clear()

    def fake_send(self, *, to_email: str, subject: str, text_body: str, html_body: str | None = None, attachments=None) -> None:
        del self, attachments
        sent_messages.append(
            {
                "to_email": to_email,
                "subject": subject,
                "text_body": text_body,
                "html_body": html_body or "",
            }
        )

    monkeypatch.setattr(EmailService, "send", fake_send)


def test_resident_sees_only_own_sessions_and_cannot_access_admin_reports() -> None:
    client = _build_client()
    headers = _login(client, username="resident1")

    sessions = client.get("/api/v1/sessions", params={"limit": 50, "offset": 0}, headers=headers)
    assert sessions.status_code == 200
    payload = sessions.json()
    assert payload["pagination"]["total"] == 1
    assert payload["items"][0]["source_key"] == "s1"

    forbidden = client.get("/api/v1/admin/reports/costs", headers=headers)
    assert forbidden.status_code == 403

    forbidden2 = client.get("/api/v1/stations", headers=headers)
    assert forbidden2.status_code == 403

    forbidden3 = client.get("/api/v1/users", headers=headers)
    assert forbidden3.status_code == 403

    forbidden4 = client.get("/api/v1/dashboard/summary", headers=headers)
    assert forbidden4.status_code == 403


def test_admin_cost_report_and_date_filters_and_csv_export() -> None:
    client = _build_client()
    headers = _login(client, username="admin")

    report = client.get("/api/v1/admin/reports/costs", headers=headers)
    assert report.status_code == 200
    payload = report.json()
    assert payload["total_sessions"] == 2
    assert payload["total_energy_wh"] == 15000
    assert payload["total_estimated_cost_eur"] == 4.5

    filtered = client.get(
        "/api/v1/admin/reports/costs",
        params={"from_date": "2026-06-05T00:00:00Z", "to_date": "2026-06-30T23:59:59Z"},
        headers=headers,
    )
    assert filtered.status_code == 200
    f = filtered.json()
    assert f["total_sessions"] == 1
    assert f["total_energy_wh"] == 5000
    assert f["total_estimated_cost_eur"] == 1.5

    csv_resp = client.get(
        "/api/v1/admin/reports/costs/export.csv",
        params={"from_date": "2026-06-01T00:00:00Z", "to_date": "2026-06-30T23:59:59Z"},
        headers=headers,
    )
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    body = csv_resp.text
    assert "resident,rfid,sessions_count,energy_kwh,estimated_cost_eur,from_date,to_date" in body
    assert "resident1,RFID-1,1,10.000,3.00" in body
    assert "resident2,RFID-2,1,5.000,1.50" in body


def test_resident_dashboard_summary_scoped_by_date() -> None:
    client = _build_client()
    headers = _login(client, username="resident2")

    summary = client.get("/api/v1/resident/summary", headers=headers)
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["total_sessions"] == 1
    assert payload["total_energy_wh"] == 5000
    assert payload["estimated_cost_eur"] == 1.5

    summary2 = client.get(
        "/api/v1/resident/summary",
        params={"from_date": "2026-06-01T00:00:00Z", "to_date": "2026-06-05T00:00:00Z"},
        headers=headers,
    )
    assert summary2.status_code == 200
    payload2 = summary2.json()
    assert payload2["total_sessions"] == 0
    assert payload2["total_energy_wh"] == 0


def test_admin_can_create_resident_only_in_own_condominium_and_resident_cannot_assign_rfid(monkeypatch) -> None:
    sent_messages: list[dict[str, str]] = []
    _enable_invitation_email(monkeypatch, sent_messages)
    client = _build_client()
    admin_headers = _login(client, username="admin")
    resident_headers = _login(client, username="resident1")
    other_admin_headers = _login(client, username="other_admin", condominium="Other Condo")

    created = client.post(
        "/api/v1/admin/residents",
        json={
            "first_name": "Mario",
            "last_name": "Rossi",
            "apartment_or_unit": "A-3",
            "email": "resident3@example.com",
            "phone_number": None,
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload["resident"]["username"] == "resident3"
    assert created_payload["resident"]["role"] == "resident"
    assert created_payload["resident"]["is_active"] is False
    assert created_payload["resident"]["condominium"]["name"] == "Condo"
    assert created_payload["invitation_sent"] is True
    assert created_payload["invitation_expires_at"]
    assert len(sent_messages) == 1

    users_same_condo = client.get("/api/v1/admin/users", headers=admin_headers)
    assert users_same_condo.status_code == 200
    assert any(user["username"] == "resident3" for user in users_same_condo.json())

    users_other_condo = client.get("/api/v1/admin/users", headers=other_admin_headers)
    assert users_other_condo.status_code == 200
    assert all(user["username"] != "resident3" for user in users_other_condo.json())

    own_rfid_users = client.get("/api/v1/admin/rfid-users", headers=admin_headers)
    assert own_rfid_users.status_code == 200
    first_rfid_id = own_rfid_users.json()[0]["id"]

    forbidden = client.post(
        f"/api/v1/admin/rfid-users/{first_rfid_id}/assign",
        json={"app_user_id": created_payload["resident"]["id"]},
        headers=resident_headers,
    )
    assert forbidden.status_code == 403


def test_admin_cannot_assign_other_condo_rfid_and_settings_update_filtered_reports_and_csv() -> None:
    client = _build_client()
    admin_headers = _login(client, username="admin")
    other_admin_headers = _login(client, username="other_admin", condominium="Other Condo")

    residents = client.get("/api/v1/admin/residents", headers=admin_headers)
    assert residents.status_code == 200
    resident1 = next(row for row in residents.json() if row["username"] == "resident1")

    own_rfid_users = client.get("/api/v1/admin/rfid-users", headers=admin_headers)
    assert own_rfid_users.status_code == 200
    card1 = next(row for row in own_rfid_users.json() if row["rfid_id"] == "RFID-1")

    other_rfid_users = client.get("/api/v1/admin/rfid-users", headers=other_admin_headers)
    assert other_rfid_users.status_code == 200
    foreign_card_id = next(row["id"] for row in other_rfid_users.json() if row["rfid_id"] == "RFID-OTHER")

    forbidden_assign = client.post(
        f"/api/v1/admin/rfid-users/{foreign_card_id}/assign",
        json={"app_user_id": resident1["app_user_id"]},
        headers=admin_headers,
    )
    assert forbidden_assign.status_code == 404

    settings = client.patch(
        "/api/v1/admin/settings",
        json={"energy_price_eur_per_kwh": 0.50},
        headers=admin_headers,
    )
    assert settings.status_code == 200
    assert settings.json()["energy_price_eur_per_kwh"] == 0.5

    filtered_report = client.get(
        "/api/v1/admin/reports/costs",
        params={
            "resident_id": resident1["app_user_id"],
            "rfid_user_id": card1["id"],
            "from_date": "2026-06-01T00:00:00Z",
            "to_date": "2026-06-30T23:59:59Z",
        },
        headers=admin_headers,
    )
    assert filtered_report.status_code == 200
    report_payload = filtered_report.json()
    assert report_payload["resident_id"] == resident1["app_user_id"]
    assert report_payload["rfid_user_id"] == card1["id"]
    assert report_payload["total_sessions"] == 1
    assert report_payload["total_energy_wh"] == 10000
    assert report_payload["total_estimated_cost_eur"] == 5.0
    assert len(report_payload["by_resident"]) == 1
    assert report_payload["by_resident"][0]["resident"] == "resident1"

    csv_resp = client.get(
        "/api/v1/admin/reports/costs/export.csv",
        params={
            "resident_id": resident1["app_user_id"],
            "rfid_user_id": card1["id"],
            "from_date": "2026-06-01T00:00:00Z",
            "to_date": "2026-06-30T23:59:59Z",
        },
        headers=admin_headers,
    )
    assert csv_resp.status_code == 200
    body = csv_resp.text
    assert "resident1,RFID-1,1,10.000,5.00" in body
    assert "resident2,RFID-2" not in body
