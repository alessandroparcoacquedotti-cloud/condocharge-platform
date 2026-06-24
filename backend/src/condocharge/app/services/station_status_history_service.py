from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from condocharge.models.charging import ChargingStation, StationStatusHistory

_FREE_STATES = {"available", "free"}
_BUSY_STATES = {"charging", "occupied", "busy"}
_UNAVAILABLE_STATES = {"faulted", "unreachable", "degraded", "offline", "unavailable"}
_KNOWN_HISTORY_SOURCES = {"agent", "live_poll", "admin_poll", "telegram_status"}
_PENDING_TRANSITIONS_KEY = "station_status_history_pending"

UNAVAILABLE_REASON_STALE_AGENT_SNAPSHOT = "stale_agent_snapshot"
UNAVAILABLE_REASON_LIVE_POLL_TIMEOUT = "live_poll_timeout"
UNAVAILABLE_REASON_LIVE_POLL_EXCEPTION = "live_poll_exception"
UNAVAILABLE_REASON_MISSING_CREDENTIALS = "missing_credentials"
UNAVAILABLE_REASON_CONNECTOR_UNKNOWN = "connector_unknown"
_KNOWN_UNAVAILABLE_REASONS = {
    UNAVAILABLE_REASON_STALE_AGENT_SNAPSHOT,
    UNAVAILABLE_REASON_LIVE_POLL_TIMEOUT,
    UNAVAILABLE_REASON_LIVE_POLL_EXCEPTION,
    UNAVAILABLE_REASON_MISSING_CREDENTIALS,
    UNAVAILABLE_REASON_CONNECTOR_UNKNOWN,
}

_transition_source_ctx: ContextVar[str | None] = ContextVar("station_status_history_source", default=None)
_transition_reason_ctx: ContextVar[str | None] = ContextVar("station_status_history_reason", default=None)


@dataclass(frozen=True)
class TransitionBaseline:
    previous_status: str
    marker: str


@dataclass(frozen=True)
class PendingTransition:
    station_id: int
    host: str
    baseline_marker: str
    previous_status: str
    new_status: str
    source: str
    reason: str
    created_at: datetime


def _normalize_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _normalize_history_status(value: str | None) -> str:
    normalized = _normalize_value(value)
    if normalized == "unknown":
        return "unknown"
    if normalized in _FREE_STATES:
        return "free"
    if normalized in _BUSY_STATES:
        return "busy"
    if normalized in _UNAVAILABLE_STATES:
        return "unavailable"
    return "unknown"


def _effective_status(*, station_status: str | None, connector_status: str | None) -> str:
    connector = _normalize_value(connector_status)
    if connector is not None:
        return _normalize_history_status(connector)
    return _normalize_history_status(station_status)


def _effective_status_from_station(station: ChargingStation) -> str:
    return _effective_status(
        station_status=getattr(station, "status", None),
        connector_status=getattr(station, "connector_status", None),
    )


def _latest_history_row(*, db: Session, station_id: int) -> StationStatusHistory | None:
    with db.no_autoflush:
        return db.scalar(
            select(StationStatusHistory)
            .where(StationStatusHistory.station_id == station_id)
            .order_by(StationStatusHistory.created_at.desc(), StationStatusHistory.id.desc())
            .limit(1)
        )


def _baseline_status(*, db: Session, station: ChargingStation) -> str:
    return _transition_baseline(db=db, station=station).previous_status


def _transition_baseline(
    *,
    db: Session,
    station: ChargingStation,
    fallback_status: str | None = None,
) -> TransitionBaseline:
    latest = _latest_history_row(db=db, station_id=station.id)
    if latest is not None:
        return TransitionBaseline(
            previous_status=_normalize_history_status(latest.new_status),
            marker=f"h:{latest.id}",
        )
    previous_status = (
        _normalize_history_status(fallback_status)
        if fallback_status is not None
        else _effective_status_from_station(station)
    )
    return TransitionBaseline(previous_status=previous_status, marker=f"i:{previous_status}")


def _infer_source_from_station(station: ChargingStation) -> str | None:
    source = _normalize_value(getattr(station, "status_source", None))
    if source == "agent":
        return "agent"
    if source == "polling":
        return "admin_poll"
    return None


def _default_reason(source: str) -> str:
    if source == "agent":
        return "agent station update"
    if source == "live_poll":
        return "live occupancy snapshot"
    if source == "admin_poll":
        return "admin station poll"
    if source == "telegram_status":
        return "telegram status snapshot"
    return "station status transition"


def normalize_unavailable_reason(reason: str | None) -> str | None:
    normalized = _normalize_value(reason)
    if normalized in _KNOWN_UNAVAILABLE_REASONS:
        return normalized
    return None


def _transition_reason(
    *,
    source: str,
    new_status: str,
    explicit_reason: str | None,
) -> str:
    if _normalize_history_status(new_status) == "unavailable":
        return normalize_unavailable_reason(explicit_reason) or UNAVAILABLE_REASON_CONNECTOR_UNKNOWN
    return (explicit_reason or _default_reason(source)).strip()


def _history_insert_statement(*, db: Session, values: dict[str, object]) -> Any:
    table = cast(Any, StationStatusHistory.__table__)
    dialect_name = db.get_bind().dialect.name
    if dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        return sqlite_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=["station_id", "baseline_marker", "new_status"]
        )
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        return postgresql_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=["station_id", "baseline_marker", "new_status"]
        )
    return table.insert().values(**values)


def _insert_transition_row(
    *,
    db: Session,
    station_id: int,
    host: str,
    baseline: TransitionBaseline,
    new_status: str,
    source: str,
    reason: str,
    created_at: datetime,
) -> None:
    values = {
        "station_id": station_id,
        "host": host,
        "baseline_marker": baseline.marker,
        "previous_status": baseline.previous_status,
        "new_status": new_status,
        "source": source,
        "reason": reason,
        "created_at": created_at,
    }
    db.execute(_history_insert_statement(db=db, values=values))


@contextmanager
def station_status_transition_context(*, source: str, reason: str | None = None) -> Iterator[None]:
    source_token = _transition_source_ctx.set(source)
    reason_token = _transition_reason_ctx.set(reason)
    try:
        yield
    finally:
        _transition_source_ctx.reset(source_token)
        _transition_reason_ctx.reset(reason_token)


def record_station_status_transition(
    *,
    db: Session,
    station: ChargingStation,
    new_status: str,
    source: str,
    previous_status: str | None = None,
    reason: str | None = None,
    created_at: datetime | None = None,
) -> StationStatusHistory | None:
    normalized_source = _normalize_value(source)
    if normalized_source not in _KNOWN_HISTORY_SOURCES:
        return None

    target_status = _normalize_history_status(new_status)
    baseline = _transition_baseline(
        db=db,
        station=station,
        fallback_status=previous_status,
    )
    if baseline.previous_status == target_status:
        return None

    timestamp = (created_at or datetime.now(tz=UTC)).astimezone(UTC)
    _insert_transition_row(
        db=db,
        station_id=station.id,
        host=station.host,
        baseline=baseline,
        new_status=target_status,
        source=normalized_source,
        reason=_transition_reason(
            source=normalized_source,
            new_status=target_status,
            explicit_reason=reason,
        ),
        created_at=timestamp,
    )
    return None


@event.listens_for(Session, "before_flush")
def _record_station_status_history_before_flush(
    db: Session,
    flush_context: object,
    instances: object,
) -> None:
    del flush_context, instances

    explicit_source = _transition_source_ctx.get()
    explicit_reason = _transition_reason_ctx.get()
    pending: dict[int, PendingTransition] = db.info.setdefault(_PENDING_TRANSITIONS_KEY, {})
    for station in db.dirty:
        if not isinstance(station, ChargingStation):
            continue

        state = inspect(station)
        if not state.persistent:
            continue

        status_history = state.attrs.status.history
        connector_history = state.attrs.connector_status.history
        if not status_history.has_changes() and not connector_history.has_changes():
            continue

        source = explicit_source or _infer_source_from_station(station)
        if source is None:
            continue

        fallback_previous_status = _effective_status(
            station_status=status_history.deleted[0] if status_history.deleted else station.status,
            connector_status=connector_history.deleted[0] if connector_history.deleted else station.connector_status,
        )
        baseline = _transition_baseline(
            db=db,
            station=station,
            fallback_status=fallback_previous_status,
        )
        new_status = _effective_status_from_station(station)
        if baseline.previous_status == new_status:
            pending.pop(station.id, None)
            continue
        pending[station.id] = PendingTransition(
            station_id=station.id,
            host=station.host,
            baseline_marker=baseline.marker,
            previous_status=baseline.previous_status,
            new_status=new_status,
            source=source,
            reason=_transition_reason(
                source=source,
                new_status=new_status,
                explicit_reason=explicit_reason,
            ),
            created_at=datetime.now(tz=UTC),
        )


@event.listens_for(Session, "after_flush_postexec")
def _persist_pending_station_status_history(
    db: Session,
    flush_context: object,
) -> None:
    del flush_context
    pending: dict[int, PendingTransition] = db.info.pop(_PENDING_TRANSITIONS_KEY, {})
    for transition in pending.values():
        _insert_transition_row(
            db=db,
            station_id=transition.station_id,
            host=transition.host,
            baseline=TransitionBaseline(
                previous_status=transition.previous_status,
                marker=transition.baseline_marker,
            ),
            new_status=transition.new_status,
            source=transition.source,
            reason=transition.reason,
            created_at=transition.created_at,
        )


@event.listens_for(Session, "after_rollback")
def _clear_pending_station_status_history(db: Session) -> None:
    db.info.pop(_PENDING_TRANSITIONS_KEY, None)
