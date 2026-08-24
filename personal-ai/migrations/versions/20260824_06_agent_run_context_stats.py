"""Persist context assembly statistics for historical run traces.

Revision ID: 20260824_06
Revises: 20260824_05
Create Date: 2026-08-24
"""

import sqlalchemy as sa
from alembic import op


revision = "20260824_06"
down_revision = "20260824_05"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("agent_runs")
    }


def upgrade() -> None:
    if "context_stats" not in _columns():
        op.add_column(
            "agent_runs",
            sa.Column("context_stats", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    if "context_stats" in _columns():
        op.drop_column("agent_runs", "context_stats")
