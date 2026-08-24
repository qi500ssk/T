"""Persist interrupted assistant drafts without feeding them back to the model.

Revision ID: 20260824_04
Revises: 20260823_03
Create Date: 2026-08-24
"""

import sqlalchemy as sa
from alembic import op


revision = "20260824_04"
down_revision = "20260823_03"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("messages")
    }


def _index_exists(name: str) -> bool:
    return any(
        index.get("name") == name
        for index in sa.inspect(op.get_bind()).get_indexes("messages")
    )


def upgrade() -> None:
    columns = _columns()
    if "run_id" not in columns:
        op.add_column("messages", sa.Column("run_id", sa.String(32), nullable=True))
    if "status" not in columns:
        op.add_column(
            "messages",
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="completed",
            ),
        )
    if not _index_exists("ix_messages_run_id"):
        op.create_index("ix_messages_run_id", "messages", ["run_id"])
    if not _index_exists("ix_messages_status"):
        op.create_index("ix_messages_status", "messages", ["status"])


def downgrade() -> None:
    if _index_exists("ix_messages_status"):
        op.drop_index("ix_messages_status", table_name="messages")
    if _index_exists("ix_messages_run_id"):
        op.drop_index("ix_messages_run_id", table_name="messages")
    columns = _columns()
    if "status" in columns:
        op.drop_column("messages", "status")
    if "run_id" in columns:
        op.drop_column("messages", "run_id")
