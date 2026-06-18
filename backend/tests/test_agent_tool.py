from __future__ import annotations

from datetime import UTC, datetime
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
        status_poll_interval_seconds=30,
        session_sync_interval_seconds=300,
        http_timeout_seconds=15.0,
        log_level="INFO",
    )
    logger = agent_tool._configure_logging(cfg)
    client = FlakyClient()
    resp = agent_tool._post_json_with_retries(
        client=client,  # type: ignore[arg-type]
        url="/api/v1/agent/heartbeat",
        headers=agent_tool._agent_headers(cfg),
        payload={"sent_at": agent_tool._iso_utc(datetime.now(tz=UTC)), "station_hosts": ["192.168.1.200"], "agent_version": "0.1.0", "hostname": "x", "started_at": agent_tool._iso_utc(datetime.now(tz=UTC)), "status_poll_interval_seconds": 30, "session_sync_interval_seconds": 300, "last_status_push_at": None, "last_session_import_at": None},
        logger=logger,
        sleep=fake_sleep,
    )
    assert resp.status_code == 200
    assert delays == [1.0, 2.0, 5.0]

