from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from condocharge.app.integrations.base.models import (
    StationStatusSnapshot,
    StationTarget,
    StationTelemetryPoint,
)
from condocharge.app.integrations.drivers.registry import DriverRegistry


class StationTargetSource(Protocol):
    def list_targets(self) -> Sequence[StationTarget]: ...


class StationStatusSink(Protocol):
    def upsert_status(self, status: StationStatusSnapshot) -> None: ...


class StationTelemetrySink(Protocol):
    def append_points(self, points: Sequence[StationTelemetryPoint]) -> None: ...


@dataclass(frozen=True)
class PollingOutcome:
    started_at: datetime
    finished_at: datetime
    polled: int
    failed: int


class StationPollingService:
    def __init__(
        self,
        *,
        registry: DriverRegistry,
        targets: StationTargetSource,
        status_sink: StationStatusSink,
        telemetry_sink: StationTelemetrySink,
    ) -> None:
        self._registry = registry
        self._targets = targets
        self._status_sink = status_sink
        self._telemetry_sink = telemetry_sink

    def poll_once(self, *, now: datetime | None = None) -> PollingOutcome:
        started_at = now or datetime.now(tz=UTC)
        polled = 0
        failed = 0

        for target in self._safe_targets(self._targets.list_targets()):
            try:
                driver = self._registry.create_driver(target)
                status = driver.get_status(target)
                telemetry = list(driver.get_telemetry(target))
                self._status_sink.upsert_status(status)
                self._telemetry_sink.append_points(telemetry)
                polled += 1
            except Exception:
                failed += 1

        finished_at = datetime.now(tz=UTC)
        return PollingOutcome(
            started_at=started_at,
            finished_at=finished_at,
            polled=polled,
            failed=failed,
        )

    @staticmethod
    def _safe_targets(targets: Iterable[StationTarget]) -> Iterable[StationTarget]:
        yield from targets
