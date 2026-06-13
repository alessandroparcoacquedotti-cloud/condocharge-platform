"""Charging stations, RFID users, and charging sessions

Revision ID: 0001
Revises: 
Create Date: 2026-06-09
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "charging_stations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("vendor", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("host", name="uq_charging_stations_host"),
    )

    op.create_table(
        "rfid_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("rfid_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("rfid_id", name="uq_rfid_users_rfid_id"),
    )

    op.create_table(
        "charging_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("source_key", sa.String(length=64), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("rfid_user_id", sa.Integer(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("energy_wh", sa.Integer(), nullable=False),
        sa.Column("total_minutes", sa.Integer(), nullable=False),
        sa.Column("charging_minutes", sa.Integer(), nullable=False),
        sa.Column("idle_minutes", sa.Integer(), nullable=False),
        sa.Column("plug_type", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["station_id"], ["charging_stations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rfid_user_id"], ["rfid_users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("source_key", name="uq_charging_sessions_source_key"),
        sa.UniqueConstraint("station_id", "start_time", "end_time", "energy_wh", name="uq_session_natural_key"),
    )

    op.create_index("ix_charging_sessions_station_id", "charging_sessions", ["station_id"])
    op.create_index("ix_charging_sessions_rfid_user_id", "charging_sessions", ["rfid_user_id"])
    op.create_index("ix_charging_sessions_start_time", "charging_sessions", ["start_time"])
    op.create_index("ix_charging_sessions_end_time", "charging_sessions", ["end_time"])


def downgrade() -> None:
    op.drop_index("ix_charging_sessions_end_time", table_name="charging_sessions")
    op.drop_index("ix_charging_sessions_start_time", table_name="charging_sessions")
    op.drop_index("ix_charging_sessions_rfid_user_id", table_name="charging_sessions")
    op.drop_index("ix_charging_sessions_station_id", table_name="charging_sessions")
    op.drop_table("charging_sessions")
    op.drop_table("rfid_users")
    op.drop_table("charging_stations")
