from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.api.deps import get_db_session
from condocharge.core.security import hash_password
from condocharge.db.base import Base
from condocharge.main import create_app
from condocharge.models.queue import ChargingQueueEntry, ChargingQueueSettings
from condocharge.models.tenancy import AppUser, AppUserRole, Condominium


def _build_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)

    with testing_session_local() as db:
        condo_a = Condominium(name="Queue Condo A")
        condo_b = Condominium(name="Queue Condo B")
        db.add_all([condo_a, condo_b])
        db.flush()

        db.add_all(
            [
                AppUser(
                    condominium_id=condo_a.id,
                    username="admin-a",
                    password_hash=hash_password("password123"),
                    role=AppUserRole.ADMIN.value,
                    is_active=1,
                ),
                AppUser(
                    condominium_id=condo_a.id,
                    username="resident-a1",
                    password_hash=hash_password("password123"),
                    role=AppUserRole.RESIDENT.value,
                    is_active=1,
                ),
                AppUser(
                    condominium_id=condo_a.id,
                    username="resident-a2",
                    password_hash=hash_password("password123"),
                    role=AppUserRole.RESIDENT.value,
                    is_active=1,
                ),
                AppUser(
                    condominium_id=condo_b.id,
                    username="admin-b",
                    password_hash=hash_password("password123"),
                    role=AppUserRole.ADMIN.value,
                    is_active=1,
                ),
                AppUser(
                    condominium_id=condo_b.id,
                    username="resident-b1",
                    password_hash=hash_password("password123"),
                    role=AppUserRole.RESIDENT.value,
                    is_active=1,
                ),
            ]
        )
        db.commit()

    app = create_app()

    def override_get_db_session() -> Iterator[Session]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    return TestClient(app), testing_session_local


def _auth_headers(client: TestClient, *, username: str, condominium: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "password123", "condominium": condominium},
    )
    assert response.status_code == 200
    token = response.json()["token"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_queue_settings_default_to_disabled() -> None:
    client, session_factory = _build_client()
    headers = _auth_headers(client, username="admin-a", condominium="Queue Condo A")

    response = client.get("/api/v1/admin/queue/settings", headers=headers)

    assert response.status_code == 200
    assert response.json()["queue_enabled"] is False
    assert response.json()["waiting_count"] == 0

    with session_factory() as db:
        row = db.scalar(
            select(ChargingQueueSettings)
            .where(ChargingQueueSettings.condominium_id == 1)
            .limit(1)
        )
        assert row is not None
        assert row.queue_enabled == 0


def test_resident_join_rejected_while_queue_disabled() -> None:
    client, _ = _build_client()
    headers = _auth_headers(client, username="resident-a1", condominium="Queue Condo A")

    response = client.post("/api/v1/resident/queue", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "Queue is disabled"


def test_join_is_idempotent_and_positions_are_fifo_per_condominium() -> None:
    client, session_factory = _build_client()
    admin_headers = _auth_headers(client, username="admin-a", condominium="Queue Condo A")
    resident_a1_headers = _auth_headers(client, username="resident-a1", condominium="Queue Condo A")
    resident_a2_headers = _auth_headers(client, username="resident-a2", condominium="Queue Condo A")
    admin_b_headers = _auth_headers(client, username="admin-b", condominium="Queue Condo B")
    resident_b1_headers = _auth_headers(client, username="resident-b1", condominium="Queue Condo B")

    enable_response = client.patch("/api/v1/admin/queue/settings", headers=admin_headers, json={"queue_enabled": True})
    assert enable_response.status_code == 200
    assert enable_response.json()["queue_enabled"] is True

    first_join = client.post("/api/v1/resident/queue", headers=resident_a1_headers)
    second_join = client.post("/api/v1/resident/queue", headers=resident_a1_headers)
    third_join = client.post("/api/v1/resident/queue", headers=resident_a2_headers)

    assert first_join.status_code == 200
    assert first_join.json()["in_queue"] is True
    assert first_join.json()["position"] == 1

    assert second_join.status_code == 200
    assert second_join.json()["in_queue"] is True
    assert second_join.json()["position"] == 1

    assert third_join.status_code == 200
    assert third_join.json()["position"] == 2

    client.patch("/api/v1/admin/queue/settings", headers=admin_b_headers, json={"queue_enabled": True})
    other_condo_join = client.post("/api/v1/resident/queue", headers=resident_b1_headers)
    assert other_condo_join.status_code == 200
    assert other_condo_join.json()["position"] == 1

    with session_factory() as db:
        entries = db.scalars(
            select(ChargingQueueEntry)
            .where(ChargingQueueEntry.condominium_id == 1)
            .where(ChargingQueueEntry.status == "waiting")
            .order_by(ChargingQueueEntry.id.asc())
        ).all()
        assert len(entries) == 2


def test_leave_is_safe_and_idempotent() -> None:
    client, session_factory = _build_client()
    admin_headers = _auth_headers(client, username="admin-a", condominium="Queue Condo A")
    resident_headers = _auth_headers(client, username="resident-a1", condominium="Queue Condo A")

    client.patch("/api/v1/admin/queue/settings", headers=admin_headers, json={"queue_enabled": True})
    join_response = client.post("/api/v1/resident/queue", headers=resident_headers)
    assert join_response.status_code == 200

    leave_response = client.delete("/api/v1/resident/queue", headers=resident_headers)
    second_leave_response = client.delete("/api/v1/resident/queue", headers=resident_headers)
    status_response = client.get("/api/v1/resident/queue", headers=resident_headers)

    assert leave_response.status_code == 200
    assert leave_response.json()["in_queue"] is False
    assert second_leave_response.status_code == 200
    assert second_leave_response.json()["in_queue"] is False
    assert status_response.status_code == 200
    assert status_response.json()["position"] is None

    with session_factory() as db:
        entries = db.scalars(
            select(ChargingQueueEntry)
            .where(ChargingQueueEntry.condominium_id == 1)
            .where(ChargingQueueEntry.resident_app_user_id == 2)
            .order_by(ChargingQueueEntry.id.asc())
        ).all()
        assert len(entries) == 1
        assert entries[0].status == "left"
        assert entries[0].leave_reason == "resident_left"


def test_openapi_contains_queue_foundation_routes() -> None:
    client, _ = _build_client()

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/admin/queue/settings" in paths
    assert "/api/v1/resident/queue" in paths
