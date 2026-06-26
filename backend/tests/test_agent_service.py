from __future__ import annotations

import threading
from pathlib import Path

import pytest

from condocharge.tools.agent import AgentScheduler
from condocharge.tools import agent_service


def _set_required_env(monkeypatch: pytest.MonkeyPatch, *, log_dir: Path) -> None:
    monkeypatch.setenv("CONDOCHARGE_AGENT_API_BASE_URL", "https://example.test")
    monkeypatch.setenv("CONDOCHARGE_AGENT_TOKEN", "token-abc")
    monkeypatch.setenv("CONDOCHARGE_AGENT_ID", "agent-1")
    monkeypatch.setenv("CONDOCHARGE_AGENT_CONDOMINIUM_ID", "1")
    monkeypatch.setenv("CONDOCHARGE_AGENT_HOSTS", "192.168.1.200")
    monkeypatch.setenv("CONDOCHARGE_LEGRAND_USERNAME", "admin")
    monkeypatch.setenv("CONDOCHARGE_LEGRAND_PASSWORD", "secret")
    monkeypatch.setenv("CONDOCHARGE_AGENT_LOG_DIR", str(log_dir))
    monkeypatch.setenv("CONDOCHARGE_AGENT_STARTUP_VALIDATE", "false")


def test_run_service_logs_startup_and_shutdown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_required_env(monkeypatch, log_dir=tmp_path)

    def fake_run_forever(**_: object) -> None:
        return None

    monkeypatch.setattr(agent_service.agent_tool, "run_forever", fake_run_forever)

    exit_code = agent_service.run_service()

    assert exit_code == 0
    contents = (tmp_path / "agent.log").read_text(encoding="utf-8")
    assert "service_runtime_startup" in contents
    assert "service_runtime_shutdown" in contents


def test_run_service_can_restart_after_clean_stop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_required_env(monkeypatch, log_dir=tmp_path)
    runs = {"count": 0}

    def fake_run_forever(**_: object) -> None:
        runs["count"] += 1

    monkeypatch.setattr(agent_service.agent_tool, "run_forever", fake_run_forever)

    first = agent_service.run_service()
    second = agent_service.run_service()

    assert first == 0
    assert second == 0
    assert runs["count"] == 2


def test_pythonclass_importable_and_entrypoint_present() -> None:
    assert callable(agent_service.run_service)
    assert hasattr(agent_service, "CondoChargeAgentService")
    assert callable(getattr(agent_service, "CondoChargeAgentService"))


def test_windows_service_wrapper_initializes() -> None:
    agent_service.CondoChargeAgentService([])


def test_agent_scheduler_can_start_and_step() -> None:
    ran = {"ok": False}
    lock = threading.Lock()

    def mark() -> None:
        ran["ok"] = True

    scheduler = AgentScheduler(clock=lambda: 0.0, start_job=lambda fn: fn())
    scheduler.add_job(name="heartbeat", interval_seconds=60, lock=lock, fn=mark, on_overlap=lambda _name: None)
    scheduler.step()
    assert ran["ok"] is True
