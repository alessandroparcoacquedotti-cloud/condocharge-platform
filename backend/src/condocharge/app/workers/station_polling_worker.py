from __future__ import annotations

from condocharge.app.integrations.polling.service import StationPollingService
from condocharge.app.workers.contracts import Worker


class StationPollingWorker:
    def __init__(self, service: StationPollingService) -> None:
        self._service = service

    def run_once(self) -> None:
        self._service.poll_once()


def as_worker(service: StationPollingService) -> Worker:
    return StationPollingWorker(service)
