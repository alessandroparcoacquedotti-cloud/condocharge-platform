from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

from condocharge.app.integrations.base.models import ConnectorStatus
from condocharge.app.integrations.legrand.driver import LegrandGreenUpDriver


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _coerce_session_dt(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("Europe/Rome"))
    return value.astimezone(UTC)


def _parse_hosts(raw: str) -> list[str]:
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        if p not in out:
            out.append(p)
    return out


@dataclass(frozen=True)
class AgentConfig:
    api_base_url: str
    token: str
    agent_id: str
    condominium_id: int
    hosts: list[str]
    legrand_username: str
    legrand_password: str
    status_poll_interval_seconds: int
    session_sync_interval_seconds: int
    http_timeout_seconds: float
    log_level: str


def _required_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise ValueError(f"Missing env var: {name}")
    return value


def _optional_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    return int(raw)


def _optional_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    return float(raw)


def _load_config() -> AgentConfig:
    api_base_url = _required_env("CONDOCHARGE_AGENT_API_BASE_URL").rstrip("/")
    token = _required_env("CONDOCHARGE_AGENT_TOKEN")
    agent_id = _required_env("CONDOCHARGE_AGENT_ID")
    condominium_id = int(_required_env("CONDOCHARGE_AGENT_CONDOMINIUM_ID"))
    hosts = _parse_hosts(_required_env("CONDOCHARGE_AGENT_HOSTS"))
    if not hosts:
        raise ValueError("CONDOCHARGE_AGENT_HOSTS must contain at least one host")
    legrand_username = _required_env("CONDOCHARGE_LEGRAND_USERNAME")
    legrand_password = _required_env("CONDOCHARGE_LEGRAND_PASSWORD")

    status_poll_interval_seconds = _optional_int("CONDOCHARGE_AGENT_STATUS_POLL_INTERVAL_SECONDS", 30)
    session_sync_interval_seconds = _optional_int("CONDOCHARGE_AGENT_SESSION_SYNC_INTERVAL_SECONDS", 300)
    http_timeout_seconds = _optional_float("CONDOCHARGE_AGENT_HTTP_TIMEOUT_SECONDS", 15.0)
    log_level = (os.environ.get("CONDOCHARGE_AGENT_LOG_LEVEL") or "INFO").strip().upper()
    return AgentConfig(
        api_base_url=api_base_url,
        token=token,
        agent_id=agent_id,
        condominium_id=condominium_id,
        hosts=hosts,
        legrand_username=legrand_username,
        legrand_password=legrand_password,
        status_poll_interval_seconds=max(1, int(status_poll_interval_seconds)),
        session_sync_interval_seconds=max(1, int(session_sync_interval_seconds)),
        http_timeout_seconds=max(1.0, float(http_timeout_seconds)),
        log_level=log_level,
    )


class _JsonLogFormatter(logging.Formatter):
    def __init__(self, *, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        for secret in self._secrets:
            if secret and secret in message:
                message = message.replace(secret, "[REDACTED]")
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", None) or record.msg if isinstance(record.msg, str) else None,
            "message": message,
        }
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k
            not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
            }
        }
        if extras:
            payload["extra"] = extras
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging(cfg: AgentConfig) -> logging.Logger:
    logger = logging.getLogger("condocharge.agent")
    logger.setLevel(getattr(logging, cfg.log_level, logging.INFO))
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonLogFormatter(secrets=[cfg.token, cfg.legrand_password]))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def _agent_headers(cfg: AgentConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {cfg.token}",
        "X-CondoCharge-Agent-Id": cfg.agent_id,
        "X-CondoCharge-Condominium-Id": str(cfg.condominium_id),
    }


def _create_http_client(cfg: AgentConfig) -> httpx.Client:
    timeout = httpx.Timeout(cfg.http_timeout_seconds)
    return httpx.Client(base_url=cfg.api_base_url, timeout=timeout, follow_redirects=True)


def _retry_delays() -> list[float]:
    return [1.0, 2.0, 5.0, 10.0]


def _post_json_with_retries(
    *,
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    logger: logging.Logger,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    delays = _retry_delays()
    last_exc: Exception | None = None
    for attempt in range(len(delays) + 1):
        try:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code >= 500 or resp.status_code == 429:
                if attempt < len(delays):
                    logger.warning(
                        "railway_request_retry",
                        extra={"event": "railway_request_retry", "url": url, "status_code": resp.status_code, "attempt": attempt + 1},
                    )
                    sleep(delays[attempt])
                    continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code < 500 and exc.response.status_code != 429:
                raise
            if attempt < len(delays):
                logger.warning(
                    "railway_request_retry",
                    extra={"event": "railway_request_retry", "url": url, "status_code": exc.response.status_code, "attempt": attempt + 1},
                )
                sleep(delays[attempt])
                continue
            raise
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt < len(delays):
                logger.warning(
                    "railway_request_retry",
                    extra={"event": "railway_request_retry", "url": url, "error": f"{type(exc).__name__}: {exc}", "attempt": attempt + 1},
                )
                sleep(delays[attempt])
                continue
            raise
    raise RuntimeError(f"Request failed after retries: {last_exc}")


def _infer_charging_state(*, state_text: str | None, mode_text: str | None, connector: ConnectorStatus) -> str:
    if connector == ConnectorStatus.CHARGING:
        return "charging"
    if connector == ConnectorStatus.OCCUPIED:
        return "connected"
    if connector == ConnectorStatus.AVAILABLE:
        if (mode_text or "").lower().find("complete") >= 0:
            return "complete"
        return "ready"
    s = f"{state_text or ''} {mode_text or ''}".lower()
    if any(x in s for x in ["complete", "termin", "fin"]):
        return "complete"
    if any(x in s for x in ["fault", "errore", "défaut", "defaut"]):
        return "faulted"
    return "unknown"


def _map_connector_status(connector: ConnectorStatus) -> str:
    raw = str(connector).lower()
    if raw in {"unknown", "available", "occupied", "charging", "faulted", "unavailable"}:
        return raw
    return "unknown"


def heartbeat_once(*, cfg: AgentConfig, client: httpx.Client, logger: logging.Logger) -> None:
    payload = {
        "agent_version": "0.1.0",
        "hostname": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "agent",
        "started_at": _iso_utc(_utc_now()),
        "sent_at": _iso_utc(_utc_now()),
        "station_hosts": cfg.hosts,
        "status_poll_interval_seconds": int(cfg.status_poll_interval_seconds),
        "session_sync_interval_seconds": int(cfg.session_sync_interval_seconds),
        "last_status_push_at": None,
        "last_session_import_at": None,
    }
    resp = _post_json_with_retries(
        client=client,
        url="/api/v1/agent/heartbeat",
        headers=_agent_headers(cfg),
        payload=payload,
        logger=logger,
    )
    logger.info("heartbeat_ok", extra={"event": "heartbeat_ok", "status_code": resp.status_code})


def push_status_once(
    *,
    cfg: AgentConfig,
    client: httpx.Client,
    driver: LegrandGreenUpDriver,
    logger: logging.Logger,
) -> None:
    stations: list[dict[str, Any]] = []
    for host in cfg.hosts:
        observed_at = _utc_now()
        try:
            driver.login(host, cfg.legrand_username, cfg.legrand_password)
            st = driver.get_station_status(host)
            rf = driver.get_rfid_status(host)
            connector = st.connector_status or ConnectorStatus.UNKNOWN
            stations.append(
                {
                    "host": host,
                    "observed_at": _iso_utc(observed_at),
                    "reachable": True,
                    "connector_status": _map_connector_status(connector),
                    "rfid_enabled": rf.rfid_enabled,
                    "charging_state": _infer_charging_state(state_text=st.state_text, mode_text=st.mode_text, connector=connector),
                    "last_error": None,
                    "last_status_payload": {
                        "state_text": st.state_text,
                        "mode_text": st.mode_text,
                        "max_charging_current_a": st.max_charging_current_a,
                        "cable_max_current_a": st.cable_max_current_a,
                        "requested_current_a": st.requested_current_a,
                        "instantaneous_current_a": st.instantaneous_current_a,
                        "instantaneous_power_kva": st.instantaneous_power_kva,
                        "rfid_enabled": rf.rfid_enabled,
                        "badge_programming_mode": rf.badge_programming_mode,
                        "rfid_station_state": rf.station_state,
                    },
                }
            )
        except Exception as exc:
            stations.append(
                {
                    "host": host,
                    "observed_at": _iso_utc(observed_at),
                    "reachable": False,
                    "connector_status": "unknown",
                    "rfid_enabled": None,
                    "charging_state": "offline",
                    "last_error": f"{type(exc).__name__}: {exc}",
                    "last_status_payload": None,
                }
            )

    payload = {"sent_at": _iso_utc(_utc_now()), "stations": stations}
    resp = _post_json_with_retries(
        client=client,
        url="/api/v1/agent/stations/status/batch",
        headers=_agent_headers(cfg),
        payload=payload,
        logger=logger,
    )
    data = resp.json()
    logger.info(
        "status_push_ok",
        extra={
            "event": "status_push_ok",
            "updated": data.get("updated"),
            "rejected": data.get("rejected"),
        },
    )


def import_sessions_once(
    *,
    cfg: AgentConfig,
    client: httpx.Client,
    driver: LegrandGreenUpDriver,
    logger: logging.Logger,
) -> None:
    hosts_payload: list[dict[str, Any]] = []
    for host in cfg.hosts:
        try:
            driver.login(host, cfg.legrand_username, cfg.legrand_password)
            sessions = driver.sync_charge_sessions(host)
            rows: list[dict[str, Any]] = []
            for s in sessions:
                start_time = _coerce_session_dt(s.start_time)
                end_time = _coerce_session_dt(s.end_time)
                rows.append(
                    {
                        "start_time": _iso_utc(start_time),
                        "end_time": _iso_utc(end_time),
                        "energy_wh": int(s.energy_wh),
                        "total_minutes": int(s.total_minutes),
                        "charging_minutes": int(s.charging_minutes),
                        "idle_minutes": int(s.idle_minutes),
                        "plug_type": s.plug_type,
                        "rfid_id": s.rfid_id,
                        "rfid_name": s.rfid_name,
                    }
                )
            hosts_payload.append({"host": host, "sessions": rows})
        except Exception as exc:
            logger.error(
                "session_import_host_failed",
                extra={"event": "session_import_host_failed", "host": host, "error": f"{type(exc).__name__}: {exc}"},
            )
            hosts_payload.append({"host": host, "sessions": []})

    payload = {"sent_at": _iso_utc(_utc_now()), "hosts": hosts_payload}
    resp = _post_json_with_retries(
        client=client,
        url="/api/v1/agent/sessions/import",
        headers=_agent_headers(cfg),
        payload=payload,
        logger=logger,
    )
    data = resp.json()
    logger.info(
        "session_import_ok",
        extra={
            "event": "session_import_ok",
            "sessions_imported": data.get("sessions_imported"),
            "sessions_updated": data.get("sessions_updated"),
            "duplicates_ignored": data.get("duplicates_ignored"),
            "hosts_processed": data.get("hosts_processed"),
        },
    )


def validate(
    *,
    cfg: AgentConfig,
    client: httpx.Client,
    driver: LegrandGreenUpDriver,
    logger: logging.Logger,
) -> None:
    health = client.get("/api/health")
    health.raise_for_status()
    logger.info("railway_health_ok", extra={"event": "railway_health_ok", "status_code": health.status_code})

    heartbeat_once(cfg=cfg, client=client, logger=logger)

    for host in cfg.hosts:
        driver.login(host, cfg.legrand_username, cfg.legrand_password)
        st = driver.get_station_status(host)
        rf = driver.get_rfid_status(host)
        connector = st.connector_status or ConnectorStatus.UNKNOWN
        logger.info(
            "legrand_probe_ok",
            extra={
                "event": "legrand_probe_ok",
                "host": host,
                "connector_status": str(connector),
                "rfid_enabled": rf.rfid_enabled,
            },
        )


def run_forever(
    *,
    cfg: AgentConfig,
    client_factory: Callable[[], httpx.Client],
    driver_factory: Callable[[], LegrandGreenUpDriver],
    logger: logging.Logger,
) -> None:
    status_interval = float(cfg.status_poll_interval_seconds)
    session_interval = float(cfg.session_sync_interval_seconds)

    next_status = time.time()
    next_sessions = time.time()

    while True:
        now = time.time()
        if now >= next_status:
            try:
                client = client_factory()
                driver = driver_factory()
                try:
                    heartbeat_once(cfg=cfg, client=client, logger=logger)
                    push_status_once(cfg=cfg, client=client, driver=driver, logger=logger)
                finally:
                    driver.close()
                    client.close()
            except Exception as exc:
                logger.error(
                    "status_cycle_failed",
                    extra={"event": "status_cycle_failed", "error": f"{type(exc).__name__}: {exc}"},
                )
            next_status = now + status_interval

        if now >= next_sessions:
            try:
                client = client_factory()
                driver = driver_factory()
                try:
                    import_sessions_once(cfg=cfg, client=client, driver=driver, logger=logger)
                finally:
                    driver.close()
                    client.close()
            except Exception as exc:
                logger.error(
                    "session_cycle_failed",
                    extra={"event": "session_cycle_failed", "error": f"{type(exc).__name__}: {exc}"},
                )
            next_sessions = now + session_interval

        time.sleep(0.25)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agent", description="CondoCharge local sync agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("run")
    sub.add_parser("push-status-once")
    sub.add_parser("import-sessions-once")
    sub.add_parser("heartbeat-once")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        cfg = _load_config()
    except Exception as exc:
        logging.getLogger("condocharge.agent").error(json.dumps({"event": "config_error", "error": f"{type(exc).__name__}: {exc}"}))
        return 2

    logger = _configure_logging(cfg)
    client = _create_http_client(cfg)
    driver = LegrandGreenUpDriver()
    try:
        if args.command == "validate":
            validate(cfg=cfg, client=client, driver=driver, logger=logger)
            logger.info("validate_ok", extra={"event": "validate_ok"})
            return 0
        if args.command == "heartbeat-once":
            heartbeat_once(cfg=cfg, client=client, logger=logger)
            return 0
        if args.command == "push-status-once":
            push_status_once(cfg=cfg, client=client, driver=driver, logger=logger)
            return 0
        if args.command == "import-sessions-once":
            import_sessions_once(cfg=cfg, client=client, driver=driver, logger=logger)
            return 0
        if args.command == "run":
            client.close()
            driver.close()
            run_forever(
                cfg=cfg,
                client_factory=lambda: _create_http_client(cfg),
                driver_factory=LegrandGreenUpDriver,
                logger=logger,
            )
            return 0
        logger.error("unknown_command", extra={"event": "unknown_command", "command": args.command})
        return 2
    except Exception as exc:
        logger.error("command_failed", extra={"event": "command_failed", "command": args.command, "error": f"{type(exc).__name__}: {exc}"})
        return 1
    finally:
        try:
            driver.close()
        finally:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())

