"""Add agent uptime fields

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-26
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_states", sa.Column("agent_started_at", sa.String(length=64), nullable=True))
    op.add_column(
        "agent_states", sa.Column("last_heartbeat_sent_at", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_states", "last_heartbeat_sent_at")
    op.drop_column("agent_states", "agent_started_at")
