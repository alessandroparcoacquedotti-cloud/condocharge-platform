"""Add Telegram notification support

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-19
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("condominiums", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("telegram_station_available_enabled", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column("telegram_charging_completed_enabled", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column("telegram_agent_offline_enabled", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column("telegram_agent_recovered_enabled", sa.Integer(), nullable=False, server_default="1")
        )

    with op.batch_alter_table("app_users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("telegram_chat_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("telegram_username", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("telegram_linked_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint("uq_app_users_telegram_chat_id", ["telegram_chat_id"])

    with op.batch_alter_table("resident_notification_preferences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("agent_offline", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("agent_recovered", sa.Integer(), nullable=False, server_default="1"))

    op.create_table(
        "resident_notification_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("condominium_id", sa.Integer(), nullable=False),
        sa.Column("resident_app_user_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("notification_type", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_message_id", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["condominium_id"], ["condominiums.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resident_app_user_id"], ["app_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "condominium_id",
            "channel",
            "notification_type",
            "dedupe_key",
            name="uq_resident_notification_history_dedupe",
        ),
    )
    op.create_index(
        op.f("ix_resident_notification_history_condominium_id"),
        "resident_notification_history",
        ["condominium_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resident_notification_history_resident_app_user_id"),
        "resident_notification_history",
        ["resident_app_user_id"],
        unique=False,
    )

    op.create_table(
        "resident_telegram_link_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("app_user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["app_user_id"], ["app_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_resident_telegram_link_tokens_token_hash"),
    )
    op.create_index(
        op.f("ix_resident_telegram_link_tokens_app_user_id"),
        "resident_telegram_link_tokens",
        ["app_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_resident_telegram_link_tokens_app_user_id"), table_name="resident_telegram_link_tokens")
    op.drop_table("resident_telegram_link_tokens")

    op.drop_index(op.f("ix_resident_notification_history_resident_app_user_id"), table_name="resident_notification_history")
    op.drop_index(op.f("ix_resident_notification_history_condominium_id"), table_name="resident_notification_history")
    op.drop_table("resident_notification_history")

    with op.batch_alter_table("resident_notification_preferences", schema=None) as batch_op:
        batch_op.drop_column("agent_recovered")
        batch_op.drop_column("agent_offline")

    with op.batch_alter_table("app_users", schema=None) as batch_op:
        batch_op.drop_constraint("uq_app_users_telegram_chat_id", type_="unique")
        batch_op.drop_column("telegram_linked_at")
        batch_op.drop_column("telegram_username")
        batch_op.drop_column("telegram_chat_id")

    with op.batch_alter_table("condominiums", schema=None) as batch_op:
        batch_op.drop_column("telegram_agent_recovered_enabled")
        batch_op.drop_column("telegram_agent_offline_enabled")
        batch_op.drop_column("telegram_charging_completed_enabled")
        batch_op.drop_column("telegram_station_available_enabled")
