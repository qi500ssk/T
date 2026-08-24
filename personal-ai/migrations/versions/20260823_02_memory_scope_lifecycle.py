"""Memory scope and lifecycle fields.

Revision ID: 20260823_02
Revises: 20260823_01
Create Date: 2026-08-23

全新数据库由 20260823_01 的 create_all 直接建出新 schema；已有数据库在此补列、
保守回填作用域并替换唯一约束，因此每一步都先探测再执行。
"""

import hashlib

import sqlalchemy as sa
from alembic import op


revision = "20260823_02"
down_revision = "20260823_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("memories")}
    additions = [
        sa.Column("scope_type", sa.String(20), nullable=False, server_default="global"),
        sa.Column("scope_key", sa.String(64), nullable=False, server_default="global"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("supersedes_id", sa.String(32), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extraction_version", sa.String(40), nullable=True),
        sa.Column("embedding_version", sa.String(40), nullable=True),
    ]
    for column in additions:
        if column.name not in columns:
            op.add_column("memories", column)

    supersedes_fk = [
        foreign_key
        for foreign_key in inspector.get_foreign_keys("memories")
        if foreign_key.get("referred_table") == "memories"
        and "supersedes_id" in (foreign_key.get("constrained_columns") or [])
    ]
    if not supersedes_fk:
        op.create_foreign_key(
            "memories_supersedes_id_fkey",
            "memories",
            "memories",
            ["supersedes_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # 保守回填：有来源会话的进入 conversation scope；来源会话已归属项目时
    # 确定性提升为 project scope；无来源的人工记忆保持 global。
    op.execute(
        "UPDATE memories SET scope_type = 'conversation', scope_key = source_conversation_id "
        "WHERE source_conversation_id IS NOT NULL "
        "AND scope_type = 'global' AND scope_key = 'global'"
    )
    op.execute(
        "UPDATE memories m SET scope_type = 'project', scope_key = c.project_id "
        "FROM conversations c "
        "WHERE m.source_conversation_id = c.id AND c.project_id IS NOT NULL "
        "AND m.scope_type = 'conversation' AND m.scope_key = m.source_conversation_id"
    )

    memories = sa.table(
        "memories",
        sa.column("id", sa.String),
        sa.column("content", sa.Text),
        sa.column("content_hash", sa.String),
    )
    legacy_rows = bind.execute(
        sa.select(memories.c.id, memories.c.content).where(memories.c.content_hash == "")
    ).fetchall()
    for row_id, content in legacy_rows:
        bind.execute(
            memories.update()
            .where(memories.c.id == row_id)
            .values(content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest())
        )

    constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("memories")
    }
    if "uq_memories_user_key" in constraints:
        op.drop_constraint("uq_memories_user_key", "memories", type_="unique")
    if "uq_memories_scope_key" not in constraints:
        op.create_unique_constraint(
            "uq_memories_scope_key",
            "memories",
            ["user_id", "scope_type", "scope_key", "normalized_key"],
        )

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memories_recall_scope "
        "ON memories (user_id, scope_type, scope_key, status, kind)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memories_content_trgm "
        "ON memories USING gin (content gin_trgm_ops) "
        "WHERE status = 'active' AND is_active = true"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memories_expiration "
        "ON memories (expires_at) "
        "WHERE expires_at IS NOT NULL AND status = 'active'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memories_supersedes_id "
        "ON memories (supersedes_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memories_supersedes_id")
    op.execute("DROP INDEX IF EXISTS ix_memories_expiration")
    op.execute("DROP INDEX IF EXISTS ix_memories_content_trgm")
    op.execute("DROP INDEX IF EXISTS ix_memories_recall_scope")
    op.drop_constraint("uq_memories_scope_key", "memories", type_="unique")
    op.create_unique_constraint("uq_memories_user_key", "memories", ["user_id", "normalized_key"])
    op.drop_column("memories", "embedding_version")
    op.drop_column("memories", "extraction_version")
    op.drop_column("memories", "expires_at")
    op.drop_column("memories", "last_used_at")
    op.drop_column("memories", "usage_count")
    op.drop_column("memories", "content_hash")
    op.drop_constraint("memories_supersedes_id_fkey", "memories", type_="foreignkey")
    op.drop_column("memories", "supersedes_id")
    op.drop_column("memories", "status")
    op.drop_column("memories", "scope_key")
    op.drop_column("memories", "scope_type")
