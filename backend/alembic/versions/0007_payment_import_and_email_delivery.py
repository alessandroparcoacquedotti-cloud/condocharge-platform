"""Payment import and email delivery MVP

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_users", sa.Column("email", sa.String(length=255), nullable=True))

    op.create_table(
        "billing_email_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "statement_id",
            sa.Integer(),
            sa.ForeignKey("resident_billing_statements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient_email", sa.String(length=255), nullable=False),
        sa.Column("notification_type", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body_preview", sa.String(length=4000), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_app_user_id",
            sa.Integer(),
            sa.ForeignKey("app_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_billing_email_notifications_statement_id", "billing_email_notifications", ["statement_id"])
    op.create_index(
        "ix_billing_email_notifications_created_by_app_user_id",
        "billing_email_notifications",
        ["created_by_app_user_id"],
    )

    op.create_table(
        "billing_unmatched_payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "condominium_id",
            sa.Integer(),
            sa.ForeignKey("condominiums.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_reference", sa.String(length=255), nullable=True),
        sa.Column("amount_eur", sa.Numeric(12, 2), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transaction_reference", sa.String(length=255), nullable=True),
        sa.Column("method", sa.String(length=32), nullable=True),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="unmatched"),
        sa.Column(
            "matched_statement_id",
            sa.Integer(),
            sa.ForeignKey("resident_billing_statements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_billing_unmatched_payments_condominium_id", "billing_unmatched_payments", ["condominium_id"])
    op.create_index(
        "ix_billing_unmatched_payments_matched_statement_id",
        "billing_unmatched_payments",
        ["matched_statement_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_billing_unmatched_payments_matched_statement_id", table_name="billing_unmatched_payments")
    op.drop_index("ix_billing_unmatched_payments_condominium_id", table_name="billing_unmatched_payments")
    op.drop_table("billing_unmatched_payments")

    op.drop_index("ix_billing_email_notifications_created_by_app_user_id", table_name="billing_email_notifications")
    op.drop_index("ix_billing_email_notifications_statement_id", table_name="billing_email_notifications")
    op.drop_table("billing_email_notifications")

    op.drop_column("app_users", "email")

