"""Resident ownership and cost configuration

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-09
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "condominiums",
        sa.Column(
            "energy_price_eur_per_kwh",
            sa.Numeric(10, 4),
            nullable=False,
            server_default="0.30",
        ),
    )

    with op.batch_alter_table("rfid_users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "app_user_id",
                sa.Integer(),
                sa.ForeignKey(
                    "app_users.id",
                    name="fk_rfid_users_app_user_id_app_users",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch_op.create_index("ix_rfid_users_app_user_id", ["app_user_id"])

    op.add_column("charging_stations", sa.Column("status", sa.String(length=32), nullable=False, server_default="unknown"))
    op.add_column(
        "charging_stations",
        sa.Column("status_source", sa.String(length=32), nullable=False, server_default="last_sync"),
    )
    op.add_column("charging_stations", sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("charging_stations", "last_sync_at")
    op.drop_column("charging_stations", "status_source")
    op.drop_column("charging_stations", "status")

    op.drop_index("ix_rfid_users_app_user_id", table_name="rfid_users")
    op.drop_column("rfid_users", "app_user_id")

    op.drop_column("condominiums", "energy_price_eur_per_kwh")
