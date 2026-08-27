"""Bind every conversation to a stable agent profile.

Revision ID: 20260827_08
Revises: 20260824_07
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op


revision = "20260827_08"
down_revision = "20260824_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("conversations")}
    if "agent_id" not in columns:
        op.add_column(
            "conversations",
            sa.Column("agent_id", sa.String(length=100), nullable=False, server_default="default"),
        )
    if "conversation_kind" not in columns:
        op.add_column(
            "conversations",
            sa.Column(
                "conversation_kind",
                sa.String(length=20),
                nullable=False,
                server_default="normal",
            ),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("conversations")}
    if "ix_conversations_agent_id" not in indexes:
        op.create_index("ix_conversations_agent_id", "conversations", ["agent_id"])
    if "ix_conversations_conversation_kind" not in indexes:
        op.create_index(
            "ix_conversations_conversation_kind",
            "conversations",
            ["conversation_kind"],
        )
    op.execute(
        "UPDATE conversations SET conversation_kind = 'project' WHERE project_id IS NOT NULL"
    )
    op.execute(
        """
        UPDATE conversations
        SET conversation_kind = 'activity'
        WHERE id IN (SELECT conversation_id FROM activities)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_conversation_kind", table_name="conversations")
    op.drop_index("ix_conversations_agent_id", table_name="conversations")
    op.drop_column("conversations", "conversation_kind")
    op.drop_column("conversations", "agent_id")
