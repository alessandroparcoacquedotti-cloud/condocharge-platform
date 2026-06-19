from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
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
    heartbeat_interval_seconds: int
    status_poll_interval_seconds: int
    session_sync_interval_seconds: int
    stale_threshold_seconds: int
    http_timeout_seconds: float
    log_level: str
    log_dir: Path
    log_file_name: str
    log_max_bytes: int
    log_backup_count: int


@dataclass
class AgentMetrics:
    heartbeat_count: int = 0
    polling_count: int = 0
    import_count: int = 0
    retry_count: int = 0
    failure_count: int = 0


@dataclass
class AgentRuntimeState:
    started_at: datetime
    last_heartbeat_success_at: datetime | None = None
    last_poll_success_at: datetime | None = None
    last_import_success_at: datetime | None = None
    metrics: AgentMetrics = field(default_factory=AgentMetrics)
    heartbeat_is_stale: bool = False
    polling_is_stale: bool = False


def _required_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        if name in {"CONDOCHARGE_LEGRAND_USERNAME", "CONDOCHARGE_LEGRAND_PASSWORD"}:
            raise ValueError(
                f"Missing required Legrand credential env var: {name}. "
                "Set it locally in a git-ignored .env file or process environment."
            )
        raise ValueError(f"Missing env var: {name}")
    return value


def _optional_str(name: str, default: str) -> str:
    value = (os.environ.get(name) or "").strip()
    return value or default


def _parse_env_assignment(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[7:].strip()
    if "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def _load_local_env_file() -> Path | None:
    explicit_env = (os.environ.get("CONDOCHARGE_AGENT_ENV_FILE") or "").strip()
    search_paths: list[Path] = []
    if explicit_env:
        search_paths.append(Path(explicit_env).expanduser())

    for base in [Path.cwd(), *Path.cwd().parents]:
        search_paths.append(base / ".env")

    module_root = Path(__file__).resolve()
    for base in module_root.parents:
        search_paths.append(base / ".env")

    seen: set[Path] = set()
    for env_path in search_paths:
        normalized = env_path.resolve(strict=False)
        if normalized in seen:
            continue
        seen.add(normalized)
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_assignment(line)
            if parsed is None:
                continue
            key, value = parsed
            os.environ.setdefault(key, value)
        return env_path
    return None


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


def _default_log_dir() -> Path:
    program_data = (os.environ.get("ProgramData") or "").strip()
    if program_data:
        return Path(program_data) / "CondoCharge" / "Agent" / "logs"
    return Path.cwd() / "logs"


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

    heartbeat_interval_seconds = _optional_int("CONDOCHARGE_AGENT_HEARTBEAT_INTERVAL_SECONDS", 60)
    status_poll_interval_seconds = _optional_int("CONDOCHARGE_AGENT_STATUS_POLL_INTERVAL_SECONDS", 30)
    session_sync_interval_seconds = _optional_int("CONDOCHARGE_AGENT_SESSION_SYNC_INTERVAL_SECONDS", 300)
    stale_threshold_seconds = _optional_int("CONDOCHARGE_AGENT_STALE_THRESHOLD_SECONDS", 180)
    http_timeout_seconds = _optional_float("CONDOCHARGE_AGENT_HTTP_TIMEOUT_SECONDS", 15.0)
    log_level = (os.environ.get("CONDOCHARGE_AGENT_LOG_LEVEL") or "INFO").strip().upper()
    log_dir = Path(_optional_str("CONDOCHARGE_AGENT_LOG_DIR", str(_default_log_dir()))).expanduser()
    log_file_name = _optional_str("CONDOCHARGE_AGENT_LOG_FILE_NAME", "agent.log")
    log_max_bytes = _optional_int("CONDOCHARGE_AGENT_LOG_MAX_BYTES", 5_242_880)
    log_backup_count = _optional_int("CONDOCHARGE_AGENT_LOG_BACKUP_COUNT", 10)
    return AgentConfig(
        api_base_url=api_base_url,
        token=token,
        agent_id=agent_id,
        condominium_id=condominium_id,
        hosts=hosts,
        legrand_username=legrand_username,
        legrand_password=legrand_password,
        heartbeat_interval_seconds=max(1, int(heartbeat_interval_seconds)),
        status_poll_interval_seconds=max(1, int(status_poll_interval_seconds)),
        session_sync_interval_seconds=max(1, int(session_sync_interval_seconds)),
        stale_threshold_seconds=max(1, int(stale_threshold_seconds)),
        http_timeout_seconds=max(1.0, float(http_timeout_seconds)),
        log_level=log_level,
        log_dir=log_dir,
        log_file_name=log_file_name,
        log_max_bytes=max(1_024, int(log_max_bytes)),
        log_backup_count=max(1, int(log_backup_count)),
    )


class _JsonLogFormatter(logging.Formatter):
    def __init__(self, *, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def _sanitize_value(self, value: Any) -> Any:
        if isinstance(value, str):
            sanitized = value
            for secret in self._secrets:
                if secret and secret in sanitized:
                    sanitized = sanitized.replace(secret, "[REDACTED]")
            return sanitized
        if isinstance(value, dict):
            return {k: self._sanitize_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sanitize_value(v) for v in value]
        if isinstance(value, tuple):
            return [self._sanitize_value(v) for v in value]
        return value

    def format(self, record: logging.LogRecord) -> str:
        message = self._sanitize_value(record.getMessage())
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
            payload["extra"] = self._sanitize_value(extras)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _build_log_path(cfg: AgentConfig) -> Path:
    return cfg.log_dir / cfg.log_file_name


def _configure_logging(cfg: AgentConfig, *, include_stdout: bool = True) -> logging.Logger:
    logger = logging.getLogger("condocharge.agent")
    logger.setLevel(getattr(logging, cfg.log_level, logging.INFO))
    logger.handlers.clear()
    formatter = _JsonLogFormatter(secrets=[cfg.token, cfg.legrand_password])
    cfg.log_dir.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        _build_log_path(cfg),
        maxBytes=cfg.log_max_bytes,
        backupCount=cfg.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if include_stdout:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    logger.propagate = False
    return logger


def _runtime_state() -> AgentRuntimeState:
    return AgentRuntimeState(started_at=_utc_now())


def _log_failure(logger: logging.Logger, *, event: str, exc: Exception, **extra: Any) -> None:
    logger.error(
        event,
        extra={
            "event": event,
            "error": f"{type(exc).__name__}: {exc}",
            **extra,
        },
    )


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
    metrics: AgentMetrics | None = None,
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
                    if metrics is not None:
                        metrics.retry_count += 1
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
                if metrics is not None:
                    metrics.retry_count += 1
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
                if metrics is not None:
                    metrics.retry_count += 1
                sleep(delays[attempt])
                continue
            raise
    raise RuntimeError(f"Request failed after retries: {last_exc}")


def _legrand_retry_delays() -> list[float]:
    return [1.0, 2.0, 5.0]


def _with_retries(
    *,
    op_name: str,
    fn: Callable[[], Any],
    logger: logging.Logger,
    metrics: AgentMetrics | None,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    delays = _legrand_retry_delays()
    last_exc: Exception | None = None
    for attempt in range(len(delays) + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < len(delays):
                logger.warning(
                    "temporary_failure_retry",
                    extra={
                        "event": "temporary_failure_retry",
                        "op": op_name,
                        "attempt": attempt + 1,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                if metrics is not None:
                    metrics.retry_count += 1
                sleep(delays[attempt])
                continue
            raise RuntimeError(f"{op_name} failed after retries: {type(last_exc).__name__}: {last_exc}") from last_exc


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


def _serialize_legrand_session(
    *,
    host: str,
    session: Any,
    logger: logging.Logger,
) -> dict[str, Any] | None:
    start_raw = getattr(session, "start_time", None)
    end_raw = getattr(session, "end_time", None)
    if start_raw is None or end_raw is None:
        logger.warning(
            "invalid_legrand_session_skipped",
            extra={
                "event": "invalid_legrand_session_skipped",
                "host": host,
                "start_time": str(start_raw) if start_raw is not None else None,
                "end_time": str(end_raw) if end_raw is not None else None,
                "reason": "missing_timestamp",
            },
        )
        return None

    start_time = _coerce_session_dt(start_raw)
    end_time = _coerce_session_dt(end_raw)
    if end_time < start_time:
        logger.warning(
            "invalid_legrand_session_skipped",
            extra={
                "event": "invalid_legrand_session_skipped",
                "host": host,
                "start_time": _iso_utc(start_time),
                "end_time": _iso_utc(end_time),
                "reason": "end_before_start",
            },
        )
        return None

    return {
        "start_time": _iso_utc(start_time),
        "end_time": _iso_utc(end_time),
        "energy_wh": int(session.energy_wh),
        "total_minutes": int(session.total_minutes),
        "charging_minutes": int(session.charging_minutes),
        "idle_minutes": int(session.idle_minutes),
        "plug_type": session.plug_type,
        "rfid_id": session.rfid_id,
        "rfid_name": session.rfid_name,
    }


def heartbeat_once(
    *,
    cfg: AgentConfig,
    client: httpx.Client,
    logger: logging.Logger,
    runtime_state: AgentRuntimeState | None = None,
) -> None:
    payload = {
        "agent_version": "0.1.0",
        "hostname": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "agent",
        "started_at": _iso_utc(runtime_state.started_at if runtime_state is not None else _utc_now()),
        "sent_at": _iso_utc(_utc_now()),
        "station_hosts": cfg.hosts,
        "heartbeat_interval_seconds": int(cfg.heartbeat_interval_seconds),
        "status_poll_interval_seconds": int(cfg.status_poll_interval_seconds),
        "session_sync_interval_seconds": int(cfg.session_sync_interval_seconds),
        "last_status_push_at": _iso_utc(runtime_state.last_poll_success_at) if runtime_state and runtime_state.last_poll_success_at else None,
        "last_session_import_at": _iso_utc(runtime_state.last_import_success_at) if runtime_state and runtime_state.last_import_success_at else None,
        "heartbeat_count": int(runtime_state.metrics.heartbeat_count) if runtime_state is not None else 0,
        "polling_count": int(runtime_state.metrics.polling_count) if runtime_state is not None else 0,
        "import_count": int(runtime_state.metrics.import_count) if runtime_state is not None else 0,
        "retry_count": int(runtime_state.metrics.retry_count) if runtime_state is not None else 0,
        "failure_count": int(runtime_state.metrics.failure_count) if runtime_state is not None else 0,
    }
    resp = _post_json_with_retries(
        client=client,
        url="/api/v1/agent/heartbeat",
        headers=_agent_headers(cfg),
        payload=payload,
        logger=logger,
        metrics=runtime_state.metrics if runtime_state is not None else None,
    )
    sent_at = _utc_now()
    if runtime_state is not None:
        runtime_state.last_heartbeat_success_at = sent_at
        runtime_state.metrics.heartbeat_count += 1
    logger.info(
        "heartbeat_success",
        extra={"event": "heartbeat_success", "status_code": resp.status_code, "sent_at": _iso_utc(sent_at)},
    )


def push_status_once(
    *,
    cfg: AgentConfig,
    client: httpx.Client,
    driver: LegrandGreenUpDriver,
    logger: logging.Logger,
    runtime_state: AgentRuntimeState | None = None,
) -> None:
    stations: list[dict[str, Any]] = []
    for host in cfg.hosts:
        observed_at = _utc_now()
        try:
            def fetch() -> tuple[Any, Any]:
                driver.login(host, cfg.legrand_username, cfg.legrand_password)
                return driver.get_station_status(host), driver.get_rfid_status(host)

            st, rf = _with_retries(
                op_name="legrand_poll",
                fn=fetch,
                logger=logger,
                metrics=runtime_state.metrics if runtime_state is not None else None,
            )
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
            if runtime_state is not None:
                runtime_state.metrics.failure_count += 1
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
        metrics=runtime_state.metrics if runtime_state is not None else None,
    )
    data = resp.json()
    sent_at = _utc_now()
    if runtime_state is not None:
        runtime_state.last_poll_success_at = sent_at
        runtime_state.metrics.polling_count += 1
    logger.info(
        "polling_success",
        extra={
            "event": "polling_success",
            "sent_at": _iso_utc(sent_at),
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
    runtime_state: AgentRuntimeState | None = None,
) -> None:
    hosts_payload: list[dict[str, Any]] = []
    sessions_total = 0
    sessions_valid = 0
    sessions_skipped_invalid = 0
    sessions_sent = 0
    for host in cfg.hosts:
        try:
            def fetch_sessions() -> list[Any]:
                driver.login(host, cfg.legrand_username, cfg.legrand_password)
                return driver.sync_charge_sessions(host)

            sessions = _with_retries(
                op_name="legrand_import",
                fn=fetch_sessions,
                logger=logger,
                metrics=runtime_state.metrics if runtime_state is not None else None,
            )
            sessions_total += len(sessions)
            rows: list[dict[str, Any]] = []
            for s in sessions:
                row = _serialize_legrand_session(host=host, session=s, logger=logger)
                if row is None:
                    sessions_skipped_invalid += 1
                    continue
                sessions_valid += 1
                rows.append(row)
            sessions_sent += len(rows)
            hosts_payload.append({"host": host, "sessions": rows})
        except Exception as exc:
            if runtime_state is not None:
                runtime_state.metrics.failure_count += 1
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
        metrics=runtime_state.metrics if runtime_state is not None else None,
    )
    data = resp.json()
    sent_at = _utc_now()
    if runtime_state is not None:
        runtime_state.last_import_success_at = sent_at
        runtime_state.metrics.import_count += 1
    logger.info(
        "import_success",
        extra={
            "event": "import_success",
            "sent_at": _iso_utc(sent_at),
            "sessions_total": sessions_total,
            "sessions_valid": sessions_valid,
            "sessions_skipped_invalid": sessions_skipped_invalid,
            "sessions_sent": sessions_sent,
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
    runtime_state: AgentRuntimeState | None = None,
) -> None:
    health = client.get("/api/health")
    health.raise_for_status()
    logger.info("railway_health_ok", extra={"event": "railway_health_ok", "status_code": health.status_code})

    heartbeat_once(cfg=cfg, client=client, logger=logger, runtime_state=runtime_state)

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


class AgentScheduler:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        start_job: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._clock = clock
        self._start_job = start_job or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self._jobs: list[dict[str, Any]] = []

    def add_job(
        self,
        *,
        name: str,
        interval_seconds: float,
        lock: threading.Lock,
        fn: Callable[[], None],
        on_overlap: Callable[[str], None],
    ) -> None:
        self._jobs.append(
            {
                "name": name,
                "interval": float(interval_seconds),
                "lock": lock,
                "fn": fn,
                "next_run": self._clock(),
                "on_overlap": on_overlap,
            }
        )

    def step(self) -> None:
        now = float(self._clock())
        for job in self._jobs:
            if now < float(job["next_run"]):
                continue
            scheduled_name = str(job["name"])
            scheduled_lock_id = id(job["lock"])
            job["next_run"] = now + float(job["interval"])
            lock: threading.Lock = job["lock"]
            acquired = lock.acquire(blocking=False)
            if not acquired:
                job["on_overlap"](str(job["name"]))
                continue

            runner_fn = job["fn"]
            runner_job_name = scheduled_name
            runner_lock = lock
            runner_lock_id = scheduled_lock_id

            def runner(
                fn: Callable[[], None] = runner_fn,
                job_name: str = runner_job_name,
                release_lock: threading.Lock = runner_lock,
                lock_id: int = runner_lock_id,
            ) -> None:
                try:
                    fn()
                finally:
                    release_lock.release()

            self._start_job(runner)


def _check_stale_and_log(*, cfg: AgentConfig, runtime_state: AgentRuntimeState, logger: logging.Logger) -> None:
    now = _utc_now()
    threshold = float(cfg.stale_threshold_seconds)

    heartbeat_ref = runtime_state.last_heartbeat_success_at or runtime_state.started_at
    polling_ref = runtime_state.last_poll_success_at or runtime_state.started_at

    heartbeat_age = (now - heartbeat_ref).total_seconds()
    polling_age = (now - polling_ref).total_seconds()

    heartbeat_stale = heartbeat_age > threshold
    polling_stale = polling_age > threshold

    if heartbeat_stale and not runtime_state.heartbeat_is_stale:
        runtime_state.heartbeat_is_stale = True
        runtime_state.metrics.failure_count += 1
        logger.error(
            "heartbeat_stale",
            extra={
                "event": "heartbeat_stale",
                "age_seconds": int(heartbeat_age),
                "threshold_seconds": int(threshold),
                "last_heartbeat_success_at": _iso_utc(heartbeat_ref),
            },
        )
    if (not heartbeat_stale) and runtime_state.heartbeat_is_stale:
        runtime_state.heartbeat_is_stale = False
        logger.info("heartbeat_recovered", extra={"event": "heartbeat_recovered"})

    if polling_stale and not runtime_state.polling_is_stale:
        runtime_state.polling_is_stale = True
        runtime_state.metrics.failure_count += 1
        logger.error(
            "station_update_stale",
            extra={
                "event": "station_update_stale",
                "age_seconds": int(polling_age),
                "threshold_seconds": int(threshold),
                "last_poll_success_at": _iso_utc(polling_ref),
            },
        )
    if (not polling_stale) and runtime_state.polling_is_stale:
        runtime_state.polling_is_stale = False
        logger.info("station_update_recovered", extra={"event": "station_update_recovered"})


def run_forever(
    *,
    cfg: AgentConfig,
    client_factory: Callable[[], httpx.Client],
    driver_factory: Callable[[], LegrandGreenUpDriver],
    logger: logging.Logger,
    runtime_state: AgentRuntimeState,
    stop_requested: Callable[[], bool] | None = None,
    sleep_interval_seconds: float = 0.5,
) -> None:
    logger.info(
        "agent_startup",
        extra={
            "event": "agent_startup",
            "started_at": _iso_utc(runtime_state.started_at),
            "pid": os.getpid(),
            "log_path": str(_build_log_path(cfg)),
        },
    )

    metrics_log_next = time.monotonic() + 60.0
    stale_check_next = time.monotonic() + 5.0

    polling_lock = threading.Lock()
    import_lock = threading.Lock()
    heartbeat_lock = threading.Lock()

    def on_overlap(job_name: str) -> None:
        runtime_state.metrics.failure_count += 1
        logger.warning("overlap_prevented", extra={"event": "overlap_prevented", "job": job_name})

    scheduler = AgentScheduler()

    def run_heartbeat_job() -> None:
        client = client_factory()
        try:
            heartbeat_once(cfg=cfg, client=client, logger=logger, runtime_state=runtime_state)
        except Exception as exc:
            runtime_state.metrics.failure_count += 1
            _log_failure(logger, event="heartbeat_failure", exc=exc)
        finally:
            client.close()

    def run_polling_job() -> None:
        client = client_factory()
        driver = driver_factory()
        try:
            push_status_once(cfg=cfg, client=client, driver=driver, logger=logger, runtime_state=runtime_state)
        except Exception as exc:
            runtime_state.metrics.failure_count += 1
            _log_failure(logger, event="polling_failure", exc=exc)
        finally:
            driver.close()
            client.close()

    def run_import_job() -> None:
        client = client_factory()
        driver = driver_factory()
        try:
            import_sessions_once(cfg=cfg, client=client, driver=driver, logger=logger, runtime_state=runtime_state)
        except Exception as exc:
            runtime_state.metrics.failure_count += 1
            _log_failure(logger, event="import_failure", exc=exc)
        finally:
            driver.close()
            client.close()

    scheduler.add_job(
        name="heartbeat",
        interval_seconds=float(cfg.heartbeat_interval_seconds),
        lock=heartbeat_lock,
        fn=run_heartbeat_job,
        on_overlap=on_overlap,
    )
    scheduler.add_job(
        name="polling",
        interval_seconds=float(cfg.status_poll_interval_seconds),
        lock=polling_lock,
        fn=run_polling_job,
        on_overlap=on_overlap,
    )
    scheduler.add_job(
        name="import",
        interval_seconds=float(cfg.session_sync_interval_seconds),
        lock=import_lock,
        fn=run_import_job,
        on_overlap=on_overlap,
    )

    while True:
        if stop_requested is not None and stop_requested():
            break

        scheduler.step()

        now_mono = time.monotonic()
        if now_mono >= stale_check_next:
            _check_stale_and_log(cfg=cfg, runtime_state=runtime_state, logger=logger)
            stale_check_next = now_mono + 5.0

        if now_mono >= metrics_log_next:
            m = runtime_state.metrics
            logger.info(
                "metrics_snapshot",
                extra={
                    "event": "metrics_snapshot",
                    "heartbeat_count": m.heartbeat_count,
                    "polling_count": m.polling_count,
                    "import_count": m.import_count,
                    "retry_count": m.retry_count,
                    "failure_count": m.failure_count,
                },
            )
            metrics_log_next = now_mono + 60.0

        time.sleep(sleep_interval_seconds)

    logger.info(
        "agent_shutdown",
        extra={
            "event": "agent_shutdown",
            "stopped_at": _iso_utc(_utc_now()),
            "last_heartbeat_success_at": _iso_utc(runtime_state.last_heartbeat_success_at) if runtime_state.last_heartbeat_success_at else None,
            "last_poll_success_at": _iso_utc(runtime_state.last_poll_success_at) if runtime_state.last_poll_success_at else None,
            "last_import_success_at": _iso_utc(runtime_state.last_import_success_at) if runtime_state.last_import_success_at else None,
        },
    )


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
    env_path = _load_local_env_file()
    try:
        cfg = _load_config()
    except Exception as exc:
        logging.getLogger("condocharge.agent").error(json.dumps({"event": "config_error", "error": f"{type(exc).__name__}: {exc}"}))
        return 2

    logger = _configure_logging(cfg)
    runtime_state = _runtime_state()
    if env_path is not None:
        logger.info("local_env_loaded", extra={"event": "local_env_loaded", "path": str(env_path)})
    client = _create_http_client(cfg)
    driver = LegrandGreenUpDriver()
    try:
        if args.command != "run":
            logger.info(
                "agent_startup",
                extra={
                    "event": "agent_startup",
                    "command": args.command,
                    "started_at": _iso_utc(runtime_state.started_at),
                    "pid": os.getpid(),
                    "log_path": str(_build_log_path(cfg)),
                },
            )
        if args.command == "validate":
            validate(cfg=cfg, client=client, driver=driver, logger=logger, runtime_state=runtime_state)
            logger.info("validate_ok", extra={"event": "validate_ok"})
            return 0
        if args.command == "heartbeat-once":
            heartbeat_once(cfg=cfg, client=client, logger=logger, runtime_state=runtime_state)
            return 0
        if args.command == "push-status-once":
            push_status_once(cfg=cfg, client=client, driver=driver, logger=logger, runtime_state=runtime_state)
            return 0
        if args.command == "import-sessions-once":
            import_sessions_once(cfg=cfg, client=client, driver=driver, logger=logger, runtime_state=runtime_state)
            return 0
        if args.command == "run":
            client.close()
            driver.close()
            run_forever(
                cfg=cfg,
                client_factory=lambda: _create_http_client(cfg),
                driver_factory=LegrandGreenUpDriver,
                logger=logger,
                runtime_state=runtime_state,
            )
            return 0
        logger.error("unknown_command", extra={"event": "unknown_command", "command": args.command})
        return 2
    except Exception as exc:
        _log_failure(logger, event="command_failed", exc=exc, command=args.command)
        runtime_state.metrics.failure_count += 1
        return 1
    finally:
        if args.command != "run":
            logger.info(
                "agent_shutdown",
                extra={
                    "event": "agent_shutdown",
                    "command": args.command,
                    "stopped_at": _iso_utc(_utc_now()),
                    "last_heartbeat_success_at": _iso_utc(runtime_state.last_heartbeat_success_at) if runtime_state.last_heartbeat_success_at else None,
                    "last_poll_success_at": _iso_utc(runtime_state.last_poll_success_at) if runtime_state.last_poll_success_at else None,
                    "last_import_success_at": _iso_utc(runtime_state.last_import_success_at) if runtime_state.last_import_success_at else None,
                },
            )
        try:
            driver.close()
        finally:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
