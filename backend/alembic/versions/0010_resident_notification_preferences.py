"""Resident notification preferences

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-11
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resident_notification_preferences",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "condominium_id",
            sa.Integer(),
            sa.ForeignKey("condominiums.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "app_user_id",
            sa.Integer(),
            sa.ForeignKey("app_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("charging_completed", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("station_available", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("station_back_online", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("app_user_id", name="uq_resident_notification_preferences_app_user_id"),
    )
    op.create_index(
        "ix_resident_notification_preferences_condominium_id",
        "resident_notification_preferences",
        ["condominium_id"],
    )
    op.create_index(
        "ix_resident_notification_preferences_app_user_id",
        "resident_notification_preferences",
        ["app_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_resident_notification_preferences_app_user_id", table_name="resident_notification_preferences")
    op.drop_index("ix_resident_notification_preferences_condominium_id", table_name="resident_notification_preferences")
    op.drop_table("resident_notification_preferences")

