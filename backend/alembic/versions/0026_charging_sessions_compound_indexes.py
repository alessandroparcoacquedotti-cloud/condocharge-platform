"""Compound indexes for dashboard summary

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-24
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_charging_sessions_condominium_id_start_time"),
        "charging_sessions",
        ["condominium_id", "start_time"],
        unique=False,
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_charging_sessions_condominium_id_end_time_desc "
        "ON charging_sessions (condominium_id, end_time DESC)"
    )
    op.create_index(
        op.f("ix_charging_sessions_condominium_id_rfid_user_id"),
        "charging_sessions",
        ["condominium_id", "rfid_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_charging_sessions_condominium_id_rfid_user_id"), table_name="charging_sessions")
    op.execute("DROP INDEX IF EXISTS ix_charging_sessions_condominium_id_end_time_desc")
    op.drop_index(op.f("ix_charging_sessions_condominium_id_start_time"), table_name="charging_sessions")

