from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import dataclass
from math import ceil
from threading import Lock

from fastapi import HTTPException, Request, status


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_seconds: int


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._events: dict[str, deque[float]] = {}

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def hit(self, *, bucket: str, rule: RateLimitRule) -> int | None:
        now = time.monotonic()
        cutoff = now - rule.window_seconds

        with self._lock:
            entries = self._events.setdefault(bucket, deque())
            while entries and entries[0] <= cutoff:
                entries.popleft()

            if len(entries) >= rule.limit:
                retry_after = max(1, ceil(rule.window_seconds - (now - entries[0])))
                return retry_after

            entries.append(now)
            return None


_limiter = InMemoryRateLimiter()


def reset_rate_limit_state() -> None:
    _limiter.reset()


def client_identifier_from_request(request: Request) -> str:
    for header_name in ("cf-connecting-ip", "x-forwarded-for", "x-real-ip"):
        header_value = request.headers.get(header_name, "").strip()
        if not header_value:
            continue
        if header_name == "x-forwarded-for":
            header_value = header_value.split(",", 1)[0].strip()
        if header_value:
            return header_value

    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def fingerprint_value(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        return "empty"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def enforce_rate_limit(*, bucket: str, rule: RateLimitRule, detail: str) -> None:
    retry_after = _limiter.hit(bucket=bucket, rule=rule)
    if retry_after is None:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(retry_after)},
    )
