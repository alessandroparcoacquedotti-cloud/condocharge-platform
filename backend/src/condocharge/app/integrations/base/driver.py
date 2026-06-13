from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from condocharge.app.integrations.base.models import (
    StationStatusSnapshot,
    StationTarget,
    StationTelemetryPoint,
    StationVendor,
)


@runtime_checkable
class StationDriver(Protocol):
    vendor: StationVendor

    def supports(self, target: StationTarget) -> bool: ...

    def get_status(self, target: StationTarget) -> StationStatusSnapshot: ...

    def get_telemetry(self, target: StationTarget) -> Sequence[StationTelemetryPoint]: ...

