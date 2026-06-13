from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from condocharge.api.deps import get_db_session
from condocharge.app.services.email_service import EmailService
from condocharge.core.config import get_settings
from condocharge.core.security import hash_password
from condocharge.db.base import Base
from condocharge.main import create_app
from condocharge.models.tenancy import AppUser, Condominium, ResidentInvitationToken


@dataclass
class AppHarness:
    client: TestClient
    session_factory: sessionmaker[Session]


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def invitation_email(monkeypatch) -> list[dict[str, str]]:
    sent_messages: list[dict[str, str]] = []
    monkeypatch.setenv("CONDOCHARGE_ENV", "pilot")
    monkeypatch.setenv("CONDOCHARGE_JWT_SECRET_KEY", "this-is-a-safe-pilot-secret-1234567890")
    monkeypatch.setenv("CONDOCHARGE_EMAIL_ENABLED", "true")
    monkeypatch.setenv("CONDOCHARGE_PUBLIC_URL", "https://condocharge.example")

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
    get_settings.cache_clear()
    return sent_messages


def _build_harness() -> AppHarness:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)

    with testing_session_local() as db:
        condo_a = Condominium(name="Condo A")
        condo_b = Condominium(name="Condo B")
        db.add_all([condo_a, condo_b])
        db.flush()

        db.add_all(
            [
                AppUser(
                    condominium_id=condo_a.id,
                    username="admin_a",
                    email="admin_a@example.com",
                    password_hash=hash_password("password123"),
                    role="admin",
                    is_active=1,
                ),
                AppUser(
                    condominium_id=condo_b.id,
                    username="admin_b",
                    email="admin_b@example.com",
                    password_hash=hash_password("password123"),
                    role="admin",
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
    return AppHarness(client=TestClient(app), session_factory=testing_session_local)


def _login(client: TestClient, *, username: str, condominium: str) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "password123", "condominium": condominium},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']['access_token']}"}


def _extract_token(message: dict[str, str]) -> str:
    match = re.search(r"/invite/([A-Za-z0-9_-]+)", message["text_body"])
    assert match is not None
    return match.group(1)


def _create_resident(harness: AppHarness, *, admin_headers: dict[str, str], email: str = "newresident@example.com") -> dict:
    resp = harness.client.post(
        "/api/v1/admin/residents",
        headers=admin_headers,
        json={
            "first_name": "Mario",
            "last_name": "Rossi",
            "apartment_or_unit": "A-1",
            "email": email,
            "phone_number": "+39 333 000 0000",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_token_creation_and_invitation_email_generation(invitation_email) -> None:
    harness = _build_harness()
    admin_headers = _login(harness.client, username="admin_a", condominium="Condo A")

    created = _create_resident(harness, admin_headers=admin_headers)
    resident = created["resident"]

    assert resident["username"] == "newresident"
    assert resident["is_active"] is False
    assert resident["must_change_password"] is False
    assert created["invitation_sent"] is True
    assert created["invitation_expires_at"]

    assert len(invitation_email) == 1
    message = invitation_email[0]
    token = _extract_token(message)
    assert message["to_email"] == "newresident@example.com"
    assert message["subject"] == "Welcome to CondoCharge"
    assert "Condo A" in message["text_body"]
    assert resident["username"] in message["text_body"]
    assert f"https://condocharge.example/invite/{token}" in message["text_body"]

    with harness.session_factory() as db:
        invitation = db.scalar(select(ResidentInvitationToken).where(ResidentInvitationToken.app_user_id == resident["id"]))
        assert invitation is not None
        assert invitation.token_hash != token
        assert invitation.used_at is None


def test_invitation_completion_sets_password_and_allows_login(invitation_email) -> None:
    harness = _build_harness()
    admin_headers = _login(harness.client, username="admin_a", condominium="Condo A")
    created = _create_resident(harness, admin_headers=admin_headers)
    token = _extract_token(invitation_email[0])

    validate = harness.client.get(f"/api/v1/auth/invitation/{token}")
    assert validate.status_code == 200
    payload = validate.json()
    assert payload["valid"] is True
    assert payload["username"] == created["resident"]["username"]
    assert payload["condominium_name"] == "Condo A"

    complete = harness.client.post(
        f"/api/v1/auth/invitation/{token}/complete",
        json={"password": "newpassword123"},
    )
    assert complete.status_code == 200
    assert complete.json() == {"success": True, "username": created["resident"]["username"]}

    validate_again = harness.client.get(f"/api/v1/auth/invitation/{token}")
    assert validate_again.status_code == 200
    assert validate_again.json()["valid"] is False

    login = harness.client.post(
        "/api/v1/auth/login",
        json={"username": created["resident"]["username"], "password": "newpassword123", "condominium": "Condo A"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["is_active"] is True
    assert login.json()["user"]["must_change_password"] is False


def test_token_expiration_and_invalid_token(invitation_email) -> None:
    harness = _build_harness()
    admin_headers = _login(harness.client, username="admin_a", condominium="Condo A")
    created = _create_resident(harness, admin_headers=admin_headers)
    token = _extract_token(invitation_email[0])

    with harness.session_factory() as db:
        invitation = db.scalar(
            select(ResidentInvitationToken).where(ResidentInvitationToken.app_user_id == created["resident"]["id"])
        )
        assert invitation is not None
        invitation.expires_at = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
        db.commit()

    expired = harness.client.get(f"/api/v1/auth/invitation/{token}")
    assert expired.status_code == 200
    assert expired.json()["valid"] is False

    complete = harness.client.post(f"/api/v1/auth/invitation/{token}/complete", json={"password": "newpassword123"})
    assert complete.status_code == 400
    assert "invalid or expired" in complete.json()["detail"].lower()

    invalid = harness.client.get("/api/v1/auth/invitation/not-a-real-token")
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False


def test_token_reuse_prevention_and_resend_invitation(invitation_email) -> None:
    harness = _build_harness()
    admin_headers = _login(harness.client, username="admin_a", condominium="Condo A")
    created = _create_resident(harness, admin_headers=admin_headers)
    first_token = _extract_token(invitation_email[0])

    resend = harness.client.post(
        "/api/v1/admin/residents/invite",
        headers=admin_headers,
        json={"resident_id": created["resident"]["id"]},
    )
    assert resend.status_code == 200
    assert resend.json()["success"] is True
    assert len(invitation_email) == 2

    second_token = _extract_token(invitation_email[1])
    assert second_token != first_token

    first_validate = harness.client.get(f"/api/v1/auth/invitation/{first_token}")
    assert first_validate.status_code == 200
    assert first_validate.json()["valid"] is False

    second_complete = harness.client.post(
        f"/api/v1/auth/invitation/{second_token}/complete",
        json={"password": "newpassword123"},
    )
    assert second_complete.status_code == 200

    reuse = harness.client.post(
        f"/api/v1/auth/invitation/{second_token}/complete",
        json={"password": "otherpassword123"},
    )
    assert reuse.status_code == 400


def test_tenant_isolation_blocks_cross_condo_invitation_resend(invitation_email) -> None:
    harness = _build_harness()
    admin_a_headers = _login(harness.client, username="admin_a", condominium="Condo A")
    admin_b_headers = _login(harness.client, username="admin_b", condominium="Condo B")
    created = _create_resident(harness, admin_headers=admin_a_headers)

    forbidden = harness.client.post(
        "/api/v1/admin/residents/invite",
        headers=admin_b_headers,
        json={"resident_id": created["resident"]["id"]},
    )
    assert forbidden.status_code == 404
