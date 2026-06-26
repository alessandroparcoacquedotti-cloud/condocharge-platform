from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.api.deps import get_db_session
from condocharge.core.security import hash_password
from condocharge.db.base import Base
from condocharge.main import create_app
from condocharge.models.tenancy import AppUser, Condominium, PushSubscription


def _build_client(*, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, sessionmaker[Session]]:
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
        outsider = AppUser(
            condominium_id=condo2.id,
            username="outsider",
            password_hash=hash_password("password123"),
            role="resident",
            is_active=1,
        )
        db.add_all([admin, resident, outsider])
        db.flush()

        db.add_all(
            [
                PushSubscription(
                    user_id=resident.id,
                    endpoint="https://example.test/endpoint-1",
                    p256dh="p256dh-1",
                    auth="auth-1",
                    active=1,
                ),
                PushSubscription(
                    user_id=outsider.id,
                    endpoint="https://example.test/endpoint-2",
                    p256dh="p256dh-2",
                    auth="auth-2",
                    active=1,
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
    return TestClient(app), TestingSessionLocal


def _auth_headers(client: TestClient, *, username: str) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "password123", "condominium": "Condo One"},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_system_health_returns_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_client(monkeypatch=monkeypatch)
    monkeypatch.setattr("socket.getaddrinfo", lambda *_args, **_kwargs: [("x", "x", "x", "x", ("127.0.0.1", 443))])
    headers = _auth_headers(client, username="admin")

    resp = client.get("/api/v1/admin/system/health", headers=headers)

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["backend_ok"] is True
    assert payload["database_ok"] is True
    assert payload["railway_dns_ok"] is True
    assert payload["push_active_subscriptions"] == 1
    assert "agent_status" in payload


def test_admin_system_health_rejects_resident(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_client(monkeypatch=monkeypatch)
    headers = _auth_headers(client, username="resident")

    resp = client.get("/api/v1/admin/system/health", headers=headers)

    assert resp.status_code == 403
