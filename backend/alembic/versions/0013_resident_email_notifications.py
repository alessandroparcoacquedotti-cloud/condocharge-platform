"""Resident email notifications

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resident_email_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "condominium_id",
            sa.Integer(),
            sa.ForeignKey("condominiums.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resident_app_user_id",
            sa.Integer(),
            sa.ForeignKey("app_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("notification_type", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "condominium_id",
            "notification_type",
            "dedupe_key",
            name="uq_resident_email_notifications_dedupe",
        ),
    )
    op.create_index(
        "ix_resident_email_notifications_condominium_id",
        "resident_email_notifications",
        ["condominium_id"],
    )
    op.create_index(
        "ix_resident_email_notifications_resident_app_user_id",
        "resident_email_notifications",
        ["resident_app_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_resident_email_notifications_resident_app_user_id", table_name="resident_email_notifications")
    op.drop_index("ix_resident_email_notifications_condominium_id", table_name="resident_email_notifications")
    op.drop_table("resident_email_notifications")
