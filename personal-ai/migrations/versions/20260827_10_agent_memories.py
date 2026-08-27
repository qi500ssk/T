"""Separate long-term memories by agent profile.

Revision ID: 20260827_10
Revises: 20260827_09
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op


revision = "20260827_10"
down_revision = "20260827_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    scope_key = next(
        column
        for column in sa.inspect(op.get_bind()).get_columns("memories")
        if column["name"] == "scope_key"
    )
    if getattr(scope_key["type"], "length", None) != 100:
        op.alter_column(
            "memories",
            "scope_key",
            existing_type=scope_key["type"],
            type_=sa.String(length=100),
            existing_nullable=False,
        )
    # 旧的“全局”记忆若有来源会话，就归到该会话绑定的好友；
    # 没有来源会话的手工全局记忆继续作为公共记忆保留。
    op.execute(
        """
        UPDATE memories AS memory
        SET scope_type = 'agent', scope_key = conversation.agent_id
        FROM conversations AS conversation
        WHERE memory.scope_type = 'global'
          AND memory.scope_key = 'global'
          AND memory.source_conversation_id = conversation.id
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE memories
        SET normalized_key = LEFT('agent.' || scope_key || '.' || normalized_key, 200),
            scope_type = 'global',
            scope_key = 'global'
        WHERE scope_type = 'agent'
        """
    )
    op.alter_column(
        "memories",
        "scope_key",
        existing_type=sa.String(length=100),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
