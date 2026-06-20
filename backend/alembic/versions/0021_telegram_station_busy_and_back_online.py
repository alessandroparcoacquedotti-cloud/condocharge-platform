"""Add Telegram station busy/back-online settings

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("condominiums", schema=None) as batch_op:
        batch_op.add_column(sa.Column("telegram_station_busy_enabled", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(
            sa.Column("telegram_station_back_online_enabled", sa.Integer(), nullable=False, server_default="0")
        )

    with op.batch_alter_table("resident_notification_preferences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("station_busy", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("resident_notification_preferences", schema=None) as batch_op:
        batch_op.drop_column("station_busy")

    with op.batch_alter_table("condominiums", schema=None) as batch_op:
        batch_op.drop_column("telegram_station_back_online_enabled")
        batch_op.drop_column("telegram_station_busy_enabled")
