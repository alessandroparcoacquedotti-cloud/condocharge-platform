"""Create station status history

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-22
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "station_status_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("baseline_marker", sa.String(length=64), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=False),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["station_id"], ["charging_stations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "station_id",
            "baseline_marker",
            "new_status",
            name="uq_station_status_history_station_baseline_new",
        ),
    )
    op.create_index(op.f("ix_station_status_history_station_id"), "station_status_history", ["station_id"], unique=False)
    op.create_index(op.f("ix_station_status_history_host"), "station_status_history", ["host"], unique=False)
    op.create_index(op.f("ix_station_status_history_new_status"), "station_status_history", ["new_status"], unique=False)
    op.create_index(op.f("ix_station_status_history_source"), "station_status_history", ["source"], unique=False)
    op.create_index(op.f("ix_station_status_history_created_at"), "station_status_history", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_station_status_history_created_at"), table_name="station_status_history")
    op.drop_index(op.f("ix_station_status_history_source"), table_name="station_status_history")
    op.drop_index(op.f("ix_station_status_history_new_status"), table_name="station_status_history")
    op.drop_index(op.f("ix_station_status_history_host"), table_name="station_status_history")
    op.drop_index(op.f("ix_station_status_history_station_id"), table_name="station_status_history")
    op.drop_table("station_status_history")
