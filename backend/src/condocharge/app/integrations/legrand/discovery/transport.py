from __future__ import annotations

from typing import Protocol

from condocharge.app.integrations.legrand.discovery.models import ProbeRequest, ProbeTarget, ResponseSnapshot


class DiscoveryTransport(Protocol):
    def fetch(self, *, target: ProbeTarget, request: ProbeRequest) -> ResponseSnapshot: ...


class DisabledTransport:
    def fetch(self, *, target: ProbeTarget, request: ProbeRequest) -> ResponseSnapshot:
        raise RuntimeError("Discovery transport is disabled")
