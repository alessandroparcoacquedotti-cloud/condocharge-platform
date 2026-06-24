from __future__ import annotations

import logging
from collections.abc import Callable

import httpx

from condocharge.app.integrations.legrand.driver import LegrandGreenUpDriver
from condocharge.tools import agent as agent_tool


def _client_factory(cfg: agent_tool.AgentConfig) -> Callable[[], httpx.Client]:
    return lambda: agent_tool._create_http_client(cfg)


def _driver_factory(cfg: agent_tool.AgentConfig) -> Callable[[], LegrandGreenUpDriver]:
    return lambda: LegrandGreenUpDriver(timeout=httpx.Timeout(cfg.http_timeout_seconds), max_retries=1)


def run_service() -> int:
    logger: logging.Logger | None = None
    try:
        agent_tool._load_local_env_file()
        cfg = agent_tool._load_config()
        logger = agent_tool._configure_logging(cfg, include_stdout=False)
        logger.info(
            "service_runtime_startup",
            extra={"event": "service_runtime_startup"},
        )
        agent_tool.run_forever(
            cfg=cfg,
            client_factory=_client_factory(cfg),
            driver_factory=_driver_factory(cfg),
            logger=logger,
            runtime_state=agent_tool._runtime_state(),
        )
        logger.info(
            "service_runtime_shutdown",
            extra={"event": "service_runtime_shutdown"},
        )
        return 0
    except Exception as exc:
        if logger is not None:
            logger.error(
                "service_runtime_failure",
                extra={"event": "service_runtime_failure", "error": f"{type(exc).__name__}: {exc}"},
            )
        return 1

