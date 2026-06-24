from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from condocharge.tools import agent as agent_tool


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class _FakeRunner:
    def __init__(self) -> None:
        self.pending: list[callable] = []

    def start(self, fn: callable) -> None:
        self.pending.append(fn)


def test_scheduler_intervals_trigger_independently() -> None:
    t = {"now": 0.0}

    def clock() -> float:
        return float(t["now"])

    runner = _FakeRunner()
    scheduler = agent_tool.AgentScheduler(clock=clock, start_job=runner.start)
    polling_lock = agent_tool.threading.Lock()
    heartbeat_lock = agent_tool.threading.Lock()
    overlaps: list[str] = []

    scheduler.add_job(
        name="polling",
        interval_seconds=30.0,
        lock=polling_lock,
        fn=lambda: None,
        on_overlap=lambda name: overlaps.append(name),
    )
    scheduler.add_job(
        name="heartbeat",
        interval_seconds=60.0,
        lock=heartbeat_lock,
        fn=lambda: None,
        on_overlap=lambda name: overlaps.append(name),
    )

    scheduler.step()
    assert len(runner.pending) == 2

    t["now"] = 10.0
    scheduler.step()
    assert len(runner.pending) == 2

    t["now"] = 31.0
    scheduler.step()
    assert len(runner.pending) == 2
    assert overlaps == ["polling"]

    runner.pending.pop()()
    scheduler.step()
    assert len(overlaps) == 1


def test_scheduler_prevents_overlap_for_same_job() -> None:
    t = {"now": 0.0}

    def clock() -> float:
        return float(t["now"])

    runner = _FakeRunner()
    scheduler = agent_tool.AgentScheduler(clock=clock, start_job=runner.start)
    lock = agent_tool.threading.Lock()
    overlaps: list[str] = []

    scheduler.add_job(
        name="import",
        interval_seconds=300.0,
        lock=lock,
        fn=lambda: None,
        on_overlap=lambda name: overlaps.append(name),
    )

    scheduler.step()
    assert len(runner.pending) == 1

    t["now"] = 301.0
    scheduler.step()
    assert len(runner.pending) == 1
    assert overlaps == ["import"]

    runner.pending.pop()()
    scheduler.step()
    assert overlaps == ["import"]


def test_with_retries_increments_retry_count_and_eventually_succeeds() -> None:
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] <= 2:
            raise RuntimeError("temporary")
        return "ok"

    metrics = agent_tool.AgentMetrics()
    handler = _ListHandler()
    logger = logging.getLogger("condocharge.agent.test.retries")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    result = agent_tool._with_retries(op_name="legrand_poll", fn=flaky, logger=logger, metrics=metrics, sleep=lambda _: None)

    assert result == "ok"
    assert metrics.retry_count == 2
    retry_events = [r for r in handler.records if getattr(r, "event", "") == "temporary_failure_retry"]
    assert len(retry_events) == 2


def test_stale_detection_emits_events_and_increments_failure_count(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
        log_dir=tmp_path,
        log_file_name="agent.log",
        log_max_bytes=1_024,
        log_backup_count=2,
    )
    started_at = datetime(2026, 6, 18, 8, 0, tzinfo=UTC)
    runtime_state = agent_tool.AgentRuntimeState(started_at=started_at)

    handler = _ListHandler()
    logger = logging.getLogger("condocharge.agent.test.stale")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    monkeypatch.setattr(agent_tool, "_utc_now", lambda: started_at + timedelta(seconds=181))
    agent_tool._check_stale_and_log(cfg=cfg, runtime_state=runtime_state, logger=logger)

    events = {getattr(r, "event", "") for r in handler.records}
    assert "heartbeat_stale" in events
    assert "station_update_stale" in events
    assert runtime_state.metrics.failure_count == 2
