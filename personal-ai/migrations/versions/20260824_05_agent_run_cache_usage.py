"""Persist per-run prompt cache usage for conversation averages.

Revision ID: 20260824_05
Revises: 20260824_04
Create Date: 2026-08-24
"""

import sqlalchemy as sa
from alembic import op


revision = "20260824_05"
down_revision = "20260824_04"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("agent_runs")
    }


def upgrade() -> None:
    if "cached_input_tokens" not in _columns():
        op.add_column(
            "agent_runs",
            sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    if "cached_input_tokens" in _columns():
        op.drop_column("agent_runs", "cached_input_tokens")
