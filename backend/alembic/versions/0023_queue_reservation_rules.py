"""Add queue reservation lifecycle fields

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "charging_queue_entries",
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "charging_queue_entries",
        sa.Column("reservation_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("charging_queue_entries", "reservation_expires_at")
    op.drop_column("charging_queue_entries", "reserved_at")
