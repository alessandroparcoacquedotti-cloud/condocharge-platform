"""Collections automation and async operations

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-09
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("billing_payment_import_jobs", sa.Column("rows_processed", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("billing_payment_import_jobs", sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("billing_email_notifications") as batch_op:
        batch_op.add_column(
            sa.Column(
                "retry_of_notification_id",
                sa.Integer(),
                sa.ForeignKey(
                    "billing_email_notifications.id",
                    name="fk_billing_email_notifications_retry_of_notification_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_billing_email_notifications_retry_of_notification_id",
            ["retry_of_notification_id"],
        )

    op.create_table(
        "billing_reminder_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "condominium_id",
            sa.Integer(),
            sa.ForeignKey("condominiums.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("days_after_period_close", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repeat_every_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("max_reminders", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("min_amount_due_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("condominium_id", name="uq_billing_reminder_rules_condominium_id"),
    )
    op.create_index("ix_billing_reminder_rules_condominium_id", "billing_reminder_rules", ["condominium_id"])


def downgrade() -> None:
    op.drop_index("ix_billing_reminder_rules_condominium_id", table_name="billing_reminder_rules")
    op.drop_table("billing_reminder_rules")

    op.drop_index("ix_billing_email_notifications_retry_of_notification_id", table_name="billing_email_notifications")
    op.drop_column("billing_email_notifications", "retry_of_notification_id")

    op.drop_column("billing_payment_import_jobs", "progress_percent")
    op.drop_column("billing_payment_import_jobs", "rows_processed")
