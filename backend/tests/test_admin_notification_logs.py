from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.api.deps import get_db_session
from condocharge.core.security import hash_password
from condocharge.db.base import Base
from condocharge.main import create_app
from condocharge.models.tenancy import AppUser, Condominium, ResidentEmailNotification, ResidentNotificationPreferences


def _build_client() -> tuple[TestClient, sessionmaker[Session], dict[str, int]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)

    with testing_session_local() as db:
        condo = Condominium(name="Test Condo")
        db.add(condo)
        db.flush()

        admin = AppUser(
            condominium_id=condo.id,
            username="admin",
            password_hash=hash_password("password123"),
            role="admin",
            is_active=1,
        )
        resident = AppUser(
            condominium_id=condo.id,
            username="resident",
            email="resident@example.com",
            password_hash=hash_password("password123"),
            role="resident",
            is_active=1,
            must_change_password=0,
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
            )
        )
        db.flush()

        db.add_all(
            [
                ResidentEmailNotification(
                    condominium_id=condo.id,
                    resident_app_user_id=resident.id,
                    notification_type="charging_completed",
                    dedupe_key="session:1",
                    status="preview",
                    created_at=datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc),
                ),
                ResidentEmailNotification(
                    condominium_id=condo.id,
                    resident_app_user_id=resident.id,
                    notification_type="station_available",
                    dedupe_key="station:1:transition:2026-06-12T12:05:00Z:resident:1",
                    status="failed",
                    error_message="SMTP down",
                    created_at=datetime(2026, 6, 12, 12, 5, tzinfo=timezone.utc),
                ),
                ResidentEmailNotification(
                    condominium_id=condo.id,
                    resident_app_user_id=resident.id,
                    notification_type="station_available",
                    dedupe_key="station:1:transition:2026-06-12T12:10:00Z:resident:1",
                    status="sent",
                    sent_at=datetime(2026, 6, 12, 12, 10, tzinfo=timezone.utc),
                    created_at=datetime(2026, 6, 12, 12, 10, tzinfo=timezone.utc),
                ),
            ]
        )
        db.commit()
        ids = {"condo_id": condo.id, "admin_id": admin.id, "resident_id": resident.id}

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    return TestClient(app), testing_session_local, ids


def _login(client: TestClient, *, username: str) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "password123", "condominium": "Test Condo"},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_can_read_logs() -> None:
    client, _, ids = _build_client()
    headers = _login(client, username="admin")

    resp = client.get("/api/v1/admin/notifications/logs", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["pagination"]["total"] == 3
    assert len(payload["items"]) == 3
    assert payload["items"][0]["condominium_id"] == ids["condo_id"]
    assert payload["items"][0]["resident_app_user_id"] == ids["resident_id"]
    assert payload["items"][0]["resident_username"] == "resident"
    assert payload["items"][0]["resident_email"] == "resident@example.com"


def test_resident_gets_403() -> None:
    client, _, _ = _build_client()
    headers = _login(client, username="resident")

    resp = client.get("/api/v1/admin/notifications/logs", headers=headers)
    assert resp.status_code == 403


def test_filters_work() -> None:
    client, _, ids = _build_client()
    headers = _login(client, username="admin")

    resp = client.get(
        "/api/v1/admin/notifications/logs",
        params={"notification_type": "station_available", "status": "failed", "resident_app_user_id": ids["resident_id"]},
        headers=headers,
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["pagination"]["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["notification_type"] == "station_available"
    assert payload["items"][0]["status"] == "failed"
    assert payload["items"][0]["error_message"] == "SMTP down"


def test_pagination_works() -> None:
    client, _, _ = _build_client()
    headers = _login(client, username="admin")

    first = client.get("/api/v1/admin/notifications/logs", params={"limit": 1, "offset": 0}, headers=headers)
    assert first.status_code == 200
    p1 = first.json()
    assert p1["pagination"] == {"total": 3, "limit": 1, "offset": 0}
    assert len(p1["items"]) == 1

    second = client.get("/api/v1/admin/notifications/logs", params={"limit": 1, "offset": 1}, headers=headers)
    assert second.status_code == 200
    p2 = second.json()
    assert p2["pagination"] == {"total": 3, "limit": 1, "offset": 1}
    assert len(p2["items"]) == 1
    assert p1["items"][0]["id"] != p2["items"][0]["id"]
