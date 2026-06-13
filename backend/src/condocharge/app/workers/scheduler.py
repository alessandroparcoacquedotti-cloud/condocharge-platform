from __future__ import annotations

from datetime import timedelta

from condocharge.app.workers.contracts import ScheduledJob, Worker


class InProcessScheduler:
    def __init__(self) -> None:
        self._registrations: list[tuple[ScheduledJob, Worker]] = []

    def register(self, job: ScheduledJob, worker: Worker) -> None:
        self._registrations.append((job, worker))

    def start(self) -> None:
        raise NotImplementedError


def every_seconds(name: str, seconds: int) -> ScheduledJob:
    return ScheduledJob(name=name, every=timedelta(seconds=seconds))
