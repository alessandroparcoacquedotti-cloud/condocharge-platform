"""Bind queue reservations to a station

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("charging_queue_entries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reserved_station_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_charging_queue_entries_reserved_station_id"),
            ["reserved_station_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_charging_queue_entries_reserved_station_id_charging_stations",
            "charging_stations",
            ["reserved_station_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("charging_queue_entries", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_charging_queue_entries_reserved_station_id_charging_stations",
            type_="foreignkey",
        )
        batch_op.drop_index(batch_op.f("ix_charging_queue_entries_reserved_station_id"))
        batch_op.drop_column("reserved_station_id")
