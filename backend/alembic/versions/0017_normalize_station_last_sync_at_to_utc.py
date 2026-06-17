"""Normalize station last_sync_at timestamps to UTC

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-17
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def _parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value

    raw = str(value).strip()
    if not raw:
        return None

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, last_sync_at FROM charging_stations WHERE last_sync_at IS NOT NULL")).fetchall()

    for row in rows:
        station_id = int(row[0])
        parsed = _parse_dt(row[1])
        if parsed is None:
            continue
        normalized = _to_utc(parsed)
        bind.execute(
            sa.text("UPDATE charging_stations SET last_sync_at = :last_sync_at WHERE id = :id"),
            {"id": station_id, "last_sync_at": normalized.isoformat().replace('+00:00', 'Z')},
        )


def downgrade() -> None:
    pass
