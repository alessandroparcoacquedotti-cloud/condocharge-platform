from __future__ import annotations

import logging
import os
import sys
import traceback
from collections.abc import Callable
from threading import Event

import httpx

from condocharge.app.integrations.legrand.driver import LegrandGreenUpDriver
from condocharge.tools import agent as agent_tool

try:
    import servicemanager  # type: ignore[import-not-found]
    import win32event  # type: ignore[import-not-found]
    import win32service  # type: ignore[import-not-found]
    import win32serviceutil  # type: ignore[import-not-found]

    _BaseServiceFramework = win32serviceutil.ServiceFramework
except Exception:
    servicemanager = None
    win32event = None
    win32service = None
    win32serviceutil = None

    class _BaseServiceFramework:
        def __init__(self, *_: object, **__: object) -> None:
            return None


def _event_info(message: str) -> None:
    if servicemanager is None:
        return
    try:
        servicemanager.LogInfoMsg(message)
    except Exception:
        return


def _event_error(message: str) -> None:
    if servicemanager is None:
        return
    try:
        servicemanager.LogErrorMsg(message)
    except Exception:
        return


def _service_runtime_context(*, cfg: agent_tool.AgentConfig, env_file: str | None) -> dict[str, object]:
    return {
        "event": "service_runtime_context",
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "python_executable": sys.executable,
        "env_file": env_file,
        "api_base_url": cfg.api_base_url,
        "agent_id": cfg.agent_id,
        "condominium_id": cfg.condominium_id,
        "hosts_count": len(cfg.hosts),
        "log_dir": str(cfg.log_dir),
    }


def _startup_validate_enabled() -> bool:
    raw = (os.environ.get("CONDOCHARGE_AGENT_STARTUP_VALIDATE") or "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _startup_validate_backend(*, cfg: agent_tool.AgentConfig, logger: logging.Logger) -> None:
    client = agent_tool._create_http_client(cfg)
    try:
        resp = client.get("/api/health")
        resp.raise_for_status()
        logger.info(
            "startup_validation_health_ok",
            extra={"event": "startup_validation_health_ok", "status_code": resp.status_code},
        )
        agent_tool.heartbeat_once(cfg=cfg, client=client, logger=logger, runtime_state=agent_tool._runtime_state())
        logger.info("startup_validation_heartbeat_ok", extra={"event": "startup_validation_heartbeat_ok"})
    finally:
        client.close()


def _client_factory(cfg: agent_tool.AgentConfig) -> Callable[[], httpx.Client]:
    return lambda: agent_tool._create_http_client(cfg)


def _driver_factory(cfg: agent_tool.AgentConfig) -> Callable[[], LegrandGreenUpDriver]:
    return lambda: LegrandGreenUpDriver(timeout=httpx.Timeout(cfg.http_timeout_seconds), max_retries=1)


def run_service(*, stop_requested: Callable[[], bool] | None = None) -> int:
    logger: logging.Logger | None = None
    env_path: str | None = None
    try:
        loaded = agent_tool._load_local_env_file()
        env_path = str(loaded) if loaded is not None else None
        cfg = agent_tool._load_config()
        logger = agent_tool._configure_logging(cfg, include_stdout=False)
        logger.info(
            "service_runtime_startup",
            extra={"event": "service_runtime_startup", **_service_runtime_context(cfg=cfg, env_file=env_path)},
        )
        _event_info(f"CondoChargeAgent starting (agent_id={cfg.agent_id} condominium_id={cfg.condominium_id})")

        if _startup_validate_enabled():
            _startup_validate_backend(cfg=cfg, logger=logger)
        else:
            logger.info("startup_validation_skipped", extra={"event": "startup_validation_skipped"})
        agent_tool.run_forever(
            cfg=cfg,
            client_factory=_client_factory(cfg),
            driver_factory=_driver_factory(cfg),
            logger=logger,
            runtime_state=agent_tool._runtime_state(),
            stop_requested=stop_requested,
        )
        logger.info(
            "service_runtime_shutdown",
            extra={"event": "service_runtime_shutdown"},
        )
        _event_info("CondoChargeAgent stopped cleanly")
        return 0
    except Exception as exc:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        _event_error(f"CondoChargeAgent failed: {type(exc).__name__}: {exc}\n{tb}")
        if logger is not None:
            logger.error(
                "service_runtime_failure",
                exc_info=True,
                extra={
                    "event": "service_runtime_failure",
                    "error": f"{type(exc).__name__}: {exc}",
                    "env_file": env_path,
                },
            )
        return 1


class CondoChargeAgentService(_BaseServiceFramework):
    _svc_name_ = "CondoChargeAgent"
    _svc_display_name_ = "CondoCharge Agent"
    _svc_description_ = "Autonomous CondoCharge agent service for heartbeat, polling, and session import."

    def __init__(self, args: list[str]) -> None:
        if win32serviceutil is not None:
            try:
                super().__init__(args if args else [self._svc_name_])
            except Exception:
                pass
        else:
            super().__init__()
        self._stop_event = Event()
        self._win32_stop_handle = (
            win32event.CreateEvent(None, 0, 0, None) if win32event is not None else None
        )

    def SvcStop(self) -> None:
        _event_info("CondoChargeAgent stopping (SvcStop)")
        if win32service is not None:
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self._stop_event.set()
        if self._win32_stop_handle is not None and win32event is not None:
            win32event.SetEvent(self._win32_stop_handle)

    def SvcDoRun(self) -> None:
        _event_info("CondoChargeAgent running (SvcDoRun)")
        exit_code = run_service(stop_requested=self._stop_event.is_set)
        if exit_code != 0:
            _event_error(f"CondoChargeAgent stopped with exit_code={exit_code}")

