"""Normalize charging session timestamps to UTC

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-17
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


_ROME = ZoneInfo("Europe/Rome")


def _parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None

    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M:%S%z",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M%z",
        "%d/%m/%Y %H:%M",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_ROME)
    return dt.astimezone(UTC)


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, start_time, end_time FROM charging_sessions")).fetchall()

    for row in rows:
        session_id = int(row[0])
        start_raw = row[1]
        end_raw = row[2]

        start_dt = _parse_dt(start_raw)
        end_dt = _parse_dt(end_raw)
        if start_dt is None or end_dt is None:
            continue

        start_utc = _to_utc(start_dt)
        end_utc = _to_utc(end_dt)

        bind.execute(
            sa.text("UPDATE charging_sessions SET start_time = :start_time, end_time = :end_time WHERE id = :id"),
            {
                "id": session_id,
                "start_time": start_utc.isoformat(),
                "end_time": end_utc.isoformat(),
            },
        )


def downgrade() -> None:
    pass
