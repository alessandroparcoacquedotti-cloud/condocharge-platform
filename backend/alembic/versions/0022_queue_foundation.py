"""Add queue foundation tables

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "charging_queue_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("condominium_id", sa.Integer(), nullable=False),
        sa.Column("queue_enabled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["condominium_id"], ["condominiums.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("condominium_id"),
    )
    op.create_index(
        op.f("ix_charging_queue_settings_condominium_id"),
        "charging_queue_settings",
        ["condominium_id"],
        unique=False,
    )

    op.create_table(
        "charging_queue_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("condominium_id", sa.Integer(), nullable=False),
        sa.Column("resident_app_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="waiting"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("leave_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["condominium_id"], ["condominiums.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resident_app_user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_charging_queue_entries_condominium_id"),
        "charging_queue_entries",
        ["condominium_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_charging_queue_entries_resident_app_user_id"),
        "charging_queue_entries",
        ["resident_app_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_charging_queue_entries_joined_at"),
        "charging_queue_entries",
        ["joined_at"],
        unique=False,
    )
    op.create_index(
        "ix_charging_queue_entries_condo_status_joined",
        "charging_queue_entries",
        ["condominium_id", "status", "joined_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_charging_queue_entries_condo_resident_status",
        "charging_queue_entries",
        ["condominium_id", "resident_app_user_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_charging_queue_entries_condo_resident_status", table_name="charging_queue_entries")
    op.drop_index("ix_charging_queue_entries_condo_status_joined", table_name="charging_queue_entries")
    op.drop_index(op.f("ix_charging_queue_entries_joined_at"), table_name="charging_queue_entries")
    op.drop_index(op.f("ix_charging_queue_entries_resident_app_user_id"), table_name="charging_queue_entries")
    op.drop_index(op.f("ix_charging_queue_entries_condominium_id"), table_name="charging_queue_entries")
    op.drop_table("charging_queue_entries")

    op.drop_index(op.f("ix_charging_queue_settings_condominium_id"), table_name="charging_queue_settings")
    op.drop_table("charging_queue_settings")
