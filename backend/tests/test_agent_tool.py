from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from condocharge.app.integrations.base.models import ConnectorStatus
from condocharge.tools import agent as agent_tool


class _FakeLegrandStatus:
    def __init__(self) -> None:
        self.connector_status = ConnectorStatus.AVAILABLE
        self.state_text = "Connected"
        self.mode_text = "Ready for charging"
        self.max_charging_current_a = 16.0
        self.cable_max_current_a = 16.0
        self.requested_current_a = 16.0
        self.instantaneous_current_a = 0.0
        self.instantaneous_power_kva = 0.0


class _FakeRfidStatus:
    def __init__(self) -> None:
        self.station_state = "Connected"
        self.rfid_enabled = True
        self.badge_programming_mode = "Off"


class _FakeSession:
    def __init__(self) -> None:
        self.start_time = datetime(2026, 6, 18, 8, 0)
        self.end_time = datetime(2026, 6, 18, 9, 0)
        self.energy_wh = 5000
        self.total_minutes = 60
        self.charging_minutes = 55
        self.idle_minutes = 5
        self.plug_type = "T2"
        self.rfid_id = "ABC123"
        self.rfid_name = "Mario"


class _BrokenSession:
    def __init__(self, *, start_time: datetime | None, end_time: datetime | None) -> None:
        self.start_time = start_time
        self.end_time = end_time
        self.energy_wh = 5000
        self.total_minutes = 60
        self.charging_minutes = 55
        self.idle_minutes = 5
        self.plug_type = "T2"
        self.rfid_id = "ABC123"
        self.rfid_name = "Mario"


class FakeLegrandGreenUpDriver:
    def __init__(self, *_: Any, **__: Any) -> None:
        self.login_calls: list[str] = []

    def close(self) -> None:
        return None

    def login(self, host: str, username: str, password: str) -> None:
        del username, password
        self.login_calls.append(host)

    def get_station_status(self, host: str) -> _FakeLegrandStatus:
        del host
        return _FakeLegrandStatus()

    def get_rfid_status(self, host: str) -> _FakeRfidStatus:
        del host
        return _FakeRfidStatus()

    def sync_charge_sessions(self, host: str) -> list[_FakeSession]:
        del host
        return [_FakeSession()]


class FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.last_json: dict[str, Any] | None = None

    def close(self) -> None:
        return None

    def get(self, url: str, *_: Any, **__: Any) -> httpx.Response:
        req = httpx.Request("GET", url)
        self.calls.append(("GET", url, None))
        return httpx.Response(200, request=req, json={"status": "ok"})

    def post(self, url: str, *_: Any, **kwargs: Any) -> httpx.Response:
        payload = kwargs.get("json")
        self.calls.append(("POST", url, payload))
        self.last_json = payload
        req = httpx.Request("POST", url)
        if url.endswith("/api/v1/agent/heartbeat"):
            return httpx.Response(200, request=req, json={"ok": True})
        if url.endswith("/api/v1/agent/stations/status/batch"):
            stations = (payload or {}).get("stations") or []
            return httpx.Response(
                200,
                request=req,
                json={"ok": True, "updated": len(stations), "rejected": 0},
            )
        if url.endswith("/api/v1/agent/sessions/import"):
            return httpx.Response(
                200,
                request=req,
                json={"ok": True, "sessions_imported": 1, "sessions_updated": 0, "duplicates_ignored": 0, "hosts_processed": 1},
            )
        return httpx.Response(404, request=req, json={"detail": "not found"})


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONDOCHARGE_AGENT_API_BASE_URL", "https://example.test")
    monkeypatch.setenv("CONDOCHARGE_AGENT_TOKEN", "token-abc")
    monkeypatch.setenv("CONDOCHARGE_AGENT_ID", "agent-1")
    monkeypatch.setenv("CONDOCHARGE_AGENT_CONDOMINIUM_ID", "1")
    monkeypatch.setenv("CONDOCHARGE_AGENT_HOSTS", "192.168.1.200,192.168.1.201")
    monkeypatch.setenv("CONDOCHARGE_LEGRAND_USERNAME", "admin")
    monkeypatch.setenv("CONDOCHARGE_LEGRAND_PASSWORD", "secret")


def test_validate_command_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    fake_client = FakeHttpClient()
    monkeypatch.setattr(agent_tool, "_create_http_client", lambda cfg: fake_client)
    monkeypatch.setattr(agent_tool, "LegrandGreenUpDriver", FakeLegrandGreenUpDriver)
    assert agent_tool.main(["validate"]) == 0
    assert any(c[0] == "GET" and c[1] == "/api/health" for c in fake_client.calls)
    assert any(c[0] == "POST" and c[1] == "/api/v1/agent/heartbeat" for c in fake_client.calls)


def test_heartbeat_once_command(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    fake_client = FakeHttpClient()
    monkeypatch.setattr(agent_tool, "_create_http_client", lambda cfg: fake_client)
    monkeypatch.setattr(agent_tool, "LegrandGreenUpDriver", FakeLegrandGreenUpDriver)
    assert agent_tool.main(["heartbeat-once"]) == 0
    assert any(c[0] == "POST" and c[1] == "/api/v1/agent/heartbeat" for c in fake_client.calls)


def test_push_status_once_command(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    fake_client = FakeHttpClient()
    monkeypatch.setattr(agent_tool, "_create_http_client", lambda cfg: fake_client)
    monkeypatch.setattr(agent_tool, "LegrandGreenUpDriver", FakeLegrandGreenUpDriver)
    assert agent_tool.main(["push-status-once"]) == 0
    assert any(c[0] == "POST" and c[1] == "/api/v1/agent/stations/status/batch" for c in fake_client.calls)
    payload = fake_client.last_json
    assert payload is not None
    assert len(payload["stations"]) == 2
    assert payload["stations"][0]["reachable"] is True
    assert payload["stations"][0]["connector_status"] == "available"


def test_import_sessions_once_command(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    fake_client = FakeHttpClient()
    monkeypatch.setattr(agent_tool, "_create_http_client", lambda cfg: fake_client)
    monkeypatch.setattr(agent_tool, "LegrandGreenUpDriver", FakeLegrandGreenUpDriver)
    assert agent_tool.main(["import-sessions-once"]) == 0
    assert any(c[0] == "POST" and c[1] == "/api/v1/agent/sessions/import" for c in fake_client.calls)
    payload = fake_client.last_json
    assert payload is not None
    sessions = payload["hosts"][0]["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["start_time"].endswith("Z")
    assert sessions[0]["end_time"].endswith("Z")


def test_import_sessions_once_skips_invalid_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    class MixedDriver(FakeLegrandGreenUpDriver):
        def sync_charge_sessions(self, host: str) -> list[Any]:
            del host
            return [
                _FakeSession(),
                _BrokenSession(start_time=None, end_time=datetime(2026, 6, 18, 9, 0)),
                _BrokenSession(start_time=datetime(2026, 6, 18, 10, 0), end_time=None),
                _BrokenSession(start_time=datetime(2026, 6, 18, 11, 0), end_time=datetime(2026, 6, 18, 10, 0)),
            ]

    _set_required_env(monkeypatch)
    fake_client = FakeHttpClient()
    monkeypatch.setattr(agent_tool, "_create_http_client", lambda cfg: fake_client)
    monkeypatch.setattr(agent_tool, "LegrandGreenUpDriver", MixedDriver)
    handler = _ListHandler()
    logger = agent_tool.logging.getLogger("condocharge.agent.test")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    cfg = agent_tool._load_config()
    client = fake_client
    driver = MixedDriver()
    agent_tool.import_sessions_once(cfg=cfg, client=client, driver=driver, logger=logger)

    payload = fake_client.last_json
    assert payload is not None
    assert len(payload["hosts"]) == 2
    assert all(len(host_payload["sessions"]) == 1 for host_payload in payload["hosts"])
    warnings = [r for r in handler.records if getattr(r, "event", "") == "invalid_legrand_session_skipped"]
    assert len(warnings) == 6
    reasons = {getattr(r, "reason", None) for r in warnings}
    assert reasons == {"missing_timestamp", "end_before_start"}
    summary = [r for r in handler.records if getattr(r, "event", "") == "import_success"]
    assert len(summary) == 1
    assert getattr(summary[0], "sessions_total", None) == 8
    assert getattr(summary[0], "sessions_valid", None) == 2
    assert getattr(summary[0], "sessions_skipped_invalid", None) == 6
    assert getattr(summary[0], "sessions_sent", None) == 2


def test_retry_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    class FlakyClient:
        def __init__(self) -> None:
            self.calls = 0

        def post(self, url: str, *_: Any, **__: Any) -> httpx.Response:
            self.calls += 1
            if self.calls <= 3:
                raise httpx.ConnectTimeout("timed out")
            req = httpx.Request("POST", url)
            return httpx.Response(200, request=req, json={"ok": True})

    delays: list[float] = []

    def fake_sleep(s: float) -> None:
        delays.append(float(s))

    cfg = agent_tool.AgentConfig(
        api_base_url="https://example.test",
        token="token",
        agent_id="agent",
        condominium_id=1,
        hosts=["192.168.1.200"],
        legrand_username="u",
        legrand_password="p",
        heartbeat_interval_seconds=60,
        status_poll_interval_seconds=30,
        session_sync_interval_seconds=300,
        stale_threshold_seconds=180,
        http_timeout_seconds=15.0,
        log_level="INFO",
        log_dir=Path.cwd() / "logs",
        log_file_name="agent.log",
        log_max_bytes=1_024,
        log_backup_count=2,
    )
    logger = agent_tool._configure_logging(cfg)
    client = FlakyClient()
    metrics = agent_tool.AgentMetrics()
    resp = agent_tool._post_json_with_retries(
        client=client,  # type: ignore[arg-type]
        url="/api/v1/agent/heartbeat",
        headers=agent_tool._agent_headers(cfg),
        payload={"sent_at": agent_tool._iso_utc(datetime.now(tz=UTC)), "station_hosts": ["192.168.1.200"], "agent_version": "0.1.0", "hostname": "x", "started_at": agent_tool._iso_utc(datetime.now(tz=UTC)), "status_poll_interval_seconds": 30, "session_sync_interval_seconds": 300, "last_status_push_at": None, "last_session_import_at": None},
        logger=logger,
        metrics=metrics,
        sleep=fake_sleep,
    )
    assert resp.status_code == 200
    assert delays == [1.0, 2.0, 5.0]
    assert metrics.retry_count == 3


def test_configure_logging_writes_rotating_file_and_redacts_secrets(tmp_path: Path) -> None:
    cfg = agent_tool.AgentConfig(
        api_base_url="https://example.test",
        token="token-secret",
        agent_id="agent",
        condominium_id=1,
        hosts=["192.168.1.200"],
        legrand_username="u",
        legrand_password="pw-secret",
        heartbeat_interval_seconds=60,
        status_poll_interval_seconds=30,
        session_sync_interval_seconds=300,
        stale_threshold_seconds=180,
        http_timeout_seconds=15.0,
        log_level="INFO",
        log_dir=tmp_path,
        log_file_name="agent.log",
        log_max_bytes=1_024,
        log_backup_count=2,
    )
    logger = agent_tool._configure_logging(cfg, include_stdout=False)
    logger.info(
        "test_log_secret",
        extra={"event": "test_log_secret", "token_value": "token-secret", "password_value": "pw-secret"},
    )
    for handler in logger.handlers:
        handler.flush()

    contents = (tmp_path / "agent.log").read_text(encoding="utf-8")
    assert "token-secret" not in contents
    assert "pw-secret" not in contents
    assert "[REDACTED]" in contents


def test_heartbeat_once_uses_runtime_state_for_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    cfg = agent_tool._load_config()
    runtime_state = agent_tool.AgentRuntimeState(
        started_at=datetime(2026, 6, 18, 8, 0, tzinfo=UTC),
        last_poll_success_at=datetime(2026, 6, 18, 8, 5, tzinfo=UTC),
        last_import_success_at=datetime(2026, 6, 18, 8, 10, tzinfo=UTC),
    )
    fake_client = FakeHttpClient()
    logger = agent_tool._configure_logging(cfg, include_stdout=False)

    agent_tool.heartbeat_once(cfg=cfg, client=fake_client, logger=logger, runtime_state=runtime_state)

    payload = fake_client.last_json
    assert payload is not None
    assert payload["started_at"] == "2026-06-18T08:00:00Z"
    assert payload["last_status_push_at"] == "2026-06-18T08:05:00Z"
    assert payload["last_session_import_at"] == "2026-06-18T08:10:00Z"
    assert runtime_state.last_heartbeat_success_at is not None
