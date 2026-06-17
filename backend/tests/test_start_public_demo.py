from __future__ import annotations

import sys

import pytest

import start_public_demo


def _clear_bootstrap_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONDOCHARGE_BOOTSTRAP_CONDOMINIUM_NAME", raising=False)
    monkeypatch.delenv("CONDOCHARGE_BOOTSTRAP_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("CONDOCHARGE_BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("CONDOCHARGE_BOOTSTRAP_ADMIN_EMAIL", raising=False)


def test_demo_mode_runs_demo_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    monkeypatch.setenv("CONDOCHARGE_DEPLOYMENT", "demo")
    monkeypatch.setenv("CONDOCHARGE_DEMO_CONDOMINIUM_NAME", "Riverview Residences")
    _clear_bootstrap_env(monkeypatch)
    monkeypatch.setattr(start_public_demo, "_run", lambda command, env: commands.append(command))
    monkeypatch.setattr(start_public_demo.os, "name", "nt", raising=False)

    start_public_demo.main()

    assert commands == [
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        [
            sys.executable,
            "-m",
            "condocharge.tools.demo_seed",
            "--mode",
            "demo",
            "--condominium-name",
            "Riverview Residences",
        ],
        [
            sys.executable,
            "-m",
            "uvicorn",
            "condocharge.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
    ]


def test_production_mode_does_not_run_demo_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    monkeypatch.setenv("CONDOCHARGE_DEPLOYMENT", "production")
    monkeypatch.setenv("CONDOCHARGE_BOOTSTRAP_CONDOMINIUM_NAME", "Condominio Parco degli Acquedotti")
    monkeypatch.setenv("CONDOCHARGE_BOOTSTRAP_ADMIN_USERNAME", "prod_admin")
    monkeypatch.setenv("CONDOCHARGE_BOOTSTRAP_ADMIN_PASSWORD", "strong-password")
    monkeypatch.setenv("CONDOCHARGE_BOOTSTRAP_ADMIN_EMAIL", "prod@example.com")
    monkeypatch.setattr(start_public_demo, "_run", lambda command, env: commands.append(command))
    monkeypatch.setattr(start_public_demo.os, "name", "nt", raising=False)

    start_public_demo.main()

    assert commands[0] == [sys.executable, "-m", "alembic", "upgrade", "head"]
    assert commands[1] == [
        sys.executable,
        "-m",
        "condocharge.tools.demo_seed",
        "--mode",
        "bootstrap",
        "--condominium-name",
        "Condominio Parco degli Acquedotti",
        "--admin-username",
        "prod_admin",
        "--admin-password",
        "strong-password",
        "--admin-email",
        "prod@example.com",
    ]
    assert "--mode" in commands[1]
    assert "demo" not in commands[1]
    assert commands[2][0:4] == [sys.executable, "-m", "uvicorn", "condocharge.main:app"]


def test_production_mode_skips_bootstrap_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    monkeypatch.setenv("CONDOCHARGE_DEPLOYMENT", "production")
    _clear_bootstrap_env(monkeypatch)
    monkeypatch.setattr(start_public_demo, "_run", lambda command, env: commands.append(command))
    monkeypatch.setattr(start_public_demo.os, "name", "nt", raising=False)

    start_public_demo.main()

    assert commands == [
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        [
            sys.executable,
            "-m",
            "uvicorn",
            "condocharge.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
    ]
