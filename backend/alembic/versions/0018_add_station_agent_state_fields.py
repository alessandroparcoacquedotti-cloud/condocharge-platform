"""Station agent state fields

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("charging_stations", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("charging_stations", sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("charging_stations", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("charging_stations", sa.Column("connector_status", sa.String(length=32), nullable=True))
    op.add_column("charging_stations", sa.Column("rfid_enabled", sa.Boolean(), nullable=True))
    op.add_column("charging_stations", sa.Column("charging_state", sa.String(length=32), nullable=True))
    op.add_column("charging_stations", sa.Column("last_status_payload_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("charging_stations", "last_status_payload_json")
    op.drop_column("charging_stations", "charging_state")
    op.drop_column("charging_stations", "rfid_enabled")
    op.drop_column("charging_stations", "connector_status")
    op.drop_column("charging_stations", "last_error")
    op.drop_column("charging_stations", "last_poll_at")
    op.drop_column("charging_stations", "last_seen_at")

