"""Payments reconciliation + notifications MVP

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("resident_billing_statements") as batch_op:
        batch_op.add_column(
            sa.Column("amount_paid_eur", sa.Numeric(12, 2), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("amount_due_eur", sa.Numeric(12, 2), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("last_reminder_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0")
        )

    op.execute(
        """
        UPDATE resident_billing_statements
        SET
          amount_paid_eur = CASE
            WHEN payment_status = 'paid' THEN amount_eur
            ELSE 0
          END,
          amount_due_eur = CASE
            WHEN payment_status = 'paid' THEN 0
            WHEN payment_status = 'waived' THEN 0
            ELSE amount_eur
          END
        """
    )

    op.create_table(
        "billing_payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "statement_id",
            sa.Integer(),
            sa.ForeignKey("resident_billing_statements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount_eur", sa.Numeric(12, 2), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("transaction_reference", sa.String(length=255), nullable=True),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by_app_user_id",
            sa.Integer(),
            sa.ForeignKey("app_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_billing_payments_statement_id", "billing_payments", ["statement_id"])
    op.create_index("ix_billing_payments_created_by_app_user_id", "billing_payments", ["created_by_app_user_id"])

    with op.batch_alter_table("resident_billing_statements") as batch_op:
        batch_op.alter_column("amount_paid_eur", server_default=None)
        batch_op.alter_column("amount_due_eur", server_default=None)
        batch_op.alter_column("reminder_count", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_billing_payments_created_by_app_user_id", table_name="billing_payments")
    op.drop_index("ix_billing_payments_statement_id", table_name="billing_payments")
    op.drop_table("billing_payments")
    op.drop_column("resident_billing_statements", "reminder_count")
    op.drop_column("resident_billing_statements", "last_reminder_at")
    op.drop_column("resident_billing_statements", "amount_due_eur")
    op.drop_column("resident_billing_statements", "amount_paid_eur")
