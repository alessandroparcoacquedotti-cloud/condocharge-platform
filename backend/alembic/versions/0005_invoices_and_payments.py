"""Invoices and resident payments MVP

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("resident_billing_statements") as batch_op:
        batch_op.add_column(
            sa.Column("statement_number", sa.String(length=64), nullable=False, server_default="TEMP")
        )
        batch_op.add_column(
            sa.Column("payment_reference", sa.String(length=128), nullable=False, server_default="TEMP")
        )

    op.create_table(
        "billing_payment_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "statement_id",
            sa.Integer(),
            sa.ForeignKey("resident_billing_statements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "changed_by_app_user_id",
            sa.Integer(),
            sa.ForeignKey("app_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("old_status", sa.String(length=32), nullable=False),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_billing_payment_events_statement_id", "billing_payment_events", ["statement_id"])
    op.create_index("ix_billing_payment_events_changed_by_app_user_id", "billing_payment_events", ["changed_by_app_user_id"])

    with op.batch_alter_table("resident_billing_statements") as batch_op:
        batch_op.alter_column("statement_number", server_default=None)
        batch_op.alter_column("payment_reference", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_billing_payment_events_changed_by_app_user_id", table_name="billing_payment_events")
    op.drop_index("ix_billing_payment_events_statement_id", table_name="billing_payment_events")
    op.drop_table("billing_payment_events")
    op.drop_column("resident_billing_statements", "payment_reference")
    op.drop_column("resident_billing_statements", "statement_number")
