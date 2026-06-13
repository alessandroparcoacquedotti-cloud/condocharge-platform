from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    every: timedelta


class Worker(Protocol):
    def run_once(self) -> None: ...


class Scheduler(Protocol):
    def register(self, job: ScheduledJob, worker: Worker) -> None: ...

    def start(self) -> None: ...
