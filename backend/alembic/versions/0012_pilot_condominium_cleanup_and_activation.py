"""Pilot condominium cleanup and activation flag

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("condominiums", sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"))

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE condominiums "
            "SET name = :new_name, updated_at = CURRENT_TIMESTAMP "
            "WHERE name = :old_name"
        ),
        {"old_name": "Real Pilot Condo", "new_name": "Condominio Parco degli Acquedotti"},
    )
    bind.execute(
        sa.text(
            "UPDATE condominiums "
            "SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
            "WHERE name = :name"
        ),
        {"name": "Default Condominium"},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE condominiums "
            "SET is_active = 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE name = :name"
        ),
        {"name": "Default Condominium"},
    )
    bind.execute(
        sa.text(
            "UPDATE condominiums "
            "SET name = :old_name, updated_at = CURRENT_TIMESTAMP "
            "WHERE name = :new_name"
        ),
        {"old_name": "Real Pilot Condo", "new_name": "Condominio Parco degli Acquedotti"},
    )

    op.drop_column("condominiums", "is_active")
