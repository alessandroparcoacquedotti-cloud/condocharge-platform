from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from condocharge.core.config import get_settings
from condocharge.main import app, create_app


def test_app_imports() -> None:
    assert app.title == "CondoCharge"


def test_pilot_startup_refuses_default_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_ENV", "pilot")
    monkeypatch.setenv("CONDOCHARGE_JWT_SECRET_KEY", "change-me")

    with pytest.raises(RuntimeError, match="Unsafe CONDOCHARGE_JWT_SECRET_KEY"):
        create_app()

    get_settings.cache_clear()


def test_pilot_startup_refuses_wildcard_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_ENV", "pilot")
    monkeypatch.setenv("CONDOCHARGE_JWT_SECRET_KEY", "this-is-a-safe-pilot-secret-1234567890")
    monkeypatch.setenv("CONDOCHARGE_CORS_ORIGINS", "[\"*\"]")

    with pytest.raises(ValidationError, match="cors_origins\\.0"):
        create_app()

    get_settings.cache_clear()


def test_pilot_cors_origin_allows_exact_origin_without_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("CONDOCHARGE_ENV", "pilot")
    monkeypatch.setenv("CONDOCHARGE_JWT_SECRET_KEY", "this-is-a-safe-pilot-secret-1234567890")
    monkeypatch.setenv("CONDOCHARGE_CORS_ORIGINS", "[\"http://localhost:5173\"]")

    client = TestClient(create_app())
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    get_settings.cache_clear()
