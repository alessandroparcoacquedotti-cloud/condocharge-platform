from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.api.deps import get_db_session
from condocharge.core.security import hash_password
from condocharge.db.base import Base
from condocharge.db.session import sanitize_database_url_for_logs, sanitize_sqlite_path_for_logs
from condocharge.main import create_app
from condocharge.models.tenancy import AppUser, Condominium, ResidentInvitationToken


def _build_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)

    with testing_session_local() as db:
        condo = Condominium(name="Condo A")
        db.add(condo)
        db.flush()

        admin = AppUser(
            condominium_id=condo.id,
            username="admin",
            email="admin@example.com",
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
        )
        invited = AppUser(
            condominium_id=condo.id,
            username="invited",
            email="invited@example.com",
            password_hash=hash_password("temp-password-123"),
            role="resident",
            is_active=0,
        )
        db.add_all([admin, resident, invited])
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


def _login(client: TestClient, *, username: str, password: str = "password123") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password, "condominium": "Condo A"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["token"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _store_invitation_token(
    session_factory: sessionmaker[Session],
    *,
    resident_username: str,
    token: str,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> None:
    now = datetime.now(tz=timezone.utc)
    created = created_at or now
    expires = expires_at or (now + timedelta(hours=24))
    with session_factory() as db:
        resident = db.scalar(select(AppUser).where(AppUser.username == resident_username))
        admin = db.scalar(select(AppUser).where(AppUser.username == "admin"))
        assert resident is not None
        assert admin is not None
        invitation = ResidentInvitationToken(
            app_user_id=resident.id,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            created_at=created,
            expires_at=expires,
            created_by_admin_id=admin.id,
        )
        db.add(invitation)
        db.commit()


def test_public_url_requires_explicit_pilot_or_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONDOCHARGE_ENV", "development")
    monkeypatch.setenv("CONDOCHARGE_PUBLIC_URL", "https://tunnel.example")
    with pytest.raises(RuntimeError, match="CONDOCHARGE_ENV must be pilot or production"):
        create_app()


def test_public_runtime_requires_https_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONDOCHARGE_ENV", "pilot")
    monkeypatch.setenv("CONDOCHARGE_JWT_SECRET_KEY", "this-is-a-safe-pilot-secret-1234567890")
    monkeypatch.setenv("CONDOCHARGE_PUBLIC_URL", "http://192.168.0.50:5173")
    with pytest.raises(RuntimeError, match="CONDOCHARGE_PUBLIC_URL must use https://"):
        create_app()


def test_explicit_lan_mode_allows_private_http_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONDOCHARGE_ENV", "development")
    monkeypatch.setenv("CONDOCHARGE_LAN_MODE", "true")
    monkeypatch.setenv("CONDOCHARGE_PUBLIC_URL", "http://192.168.0.50:5173")
    app = create_app()
    assert app.title == "CondoCharge"


def test_database_log_sanitizer_masks_credentials_and_paths() -> None:
    sanitized = sanitize_database_url_for_logs(
        "postgresql://alice:supersecret@db.example.com:5432/condocharge?sslmode=require"
    )
    assert "alice" not in sanitized
    assert "supersecret" not in sanitized
    assert "condocharge" not in sanitized
    assert "***" in sanitized

    sqlite_sanitized = sanitize_database_url_for_logs("sqlite+pysqlite:///C:/secret/path/pilot_real.sqlite3")
    assert "secret/path" not in sqlite_sanitized
    assert "pilot_real.sqlite3" in sqlite_sanitized
    assert sanitize_sqlite_path_for_logs(r"C:\secret\path\pilot_real.sqlite3") == r"...\pilot_real.sqlite3"


def test_login_rate_limit_blocks_brute_force_attempts() -> None:
    client, _ = _build_client()
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "resident", "password": "wrong-password", "condominium": "Condo A"},
        )
        assert response.status_code == 401

    blocked = client.post(
        "/api/v1/auth/login",
        json={"username": "resident", "password": "wrong-password", "condominium": "Condo A"},
    )
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"]


def test_invitation_status_rate_limit_blocks_token_spraying() -> None:
    client, _ = _build_client()
    for _ in range(30):
        response = client.get("/api/v1/auth/invitation/not-a-real-token")
        assert response.status_code == 200

    blocked = client.get("/api/v1/auth/invitation/not-a-real-token")
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"]


def test_invitation_completion_rate_limit_blocks_repeated_attempts() -> None:
    client, _ = _build_client()
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/invitation/not-a-real-token/complete",
            json={"password": "newpassword123"},
        )
        assert response.status_code == 400

    blocked = client.post(
        "/api/v1/auth/invitation/not-a-real-token/complete",
        json={"password": "newpassword123"},
    )
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"]


def test_password_change_invalidates_old_tokens() -> None:
    client, _ = _build_client()
    old_headers = _login(client, username="resident")

    changed = client.post(
        "/api/v1/auth/change-password",
        headers=old_headers,
        json={"current_password": "password123", "new_password": "newpassword123"},
    )
    assert changed.status_code == 200

    old_token_check = client.get("/api/v1/auth/me", headers=old_headers)
    assert old_token_check.status_code == 401

    new_headers = _login(client, username="resident", password="newpassword123")
    new_token_check = client.get("/api/v1/auth/me", headers=new_headers)
    assert new_token_check.status_code == 200


def test_invitation_completion_does_not_reactivate_disabled_user() -> None:
    client, session_factory = _build_client()
    issued_at = datetime.now(tz=timezone.utc) - timedelta(minutes=10)
    _store_invitation_token(session_factory, resident_username="invited", token="disabled-invite", created_at=issued_at)

    with session_factory() as db:
        invited = db.scalar(select(AppUser).where(AppUser.username == "invited"))
        assert invited is not None
        invited.is_active = 0
        invited.updated_at = datetime.now(tz=timezone.utc)
        db.commit()

    blocked = client.post(
        "/api/v1/auth/invitation/disabled-invite/complete",
        json={"password": "newpassword123"},
    )
    assert blocked.status_code == 400

    with session_factory() as db:
        invited = db.scalar(select(AppUser).where(AppUser.username == "invited"))
        assert invited is not None
        assert invited.is_active == 0


def test_invitation_completion_invalidates_existing_tokens() -> None:
    client, session_factory = _build_client()
    old_headers = _login(client, username="resident")
    _store_invitation_token(session_factory, resident_username="resident", token="resident-refresh-invite")

    completed = client.post(
        "/api/v1/auth/invitation/resident-refresh-invite/complete",
        json={"password": "brandnewpassword123"},
    )
    assert completed.status_code == 200

    old_token_check = client.get("/api/v1/auth/me", headers=old_headers)
    assert old_token_check.status_code == 401

    new_headers = _login(client, username="resident", password="brandnewpassword123")
    new_token_check = client.get("/api/v1/auth/me", headers=new_headers)
    assert new_token_check.status_code == 200
