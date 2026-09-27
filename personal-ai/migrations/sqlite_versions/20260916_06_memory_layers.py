"""世界事实与角色视角引用，不复制世界图谱。"""
from alembic import op
import sqlalchemy as sa

revision = "sqlite_20260916_06"
down_revision = "sqlite_20260915_05"
branch_labels = None
depends_on = None


def upgrade():
    from infrastructure.database import WorldFact
    connection = op.get_bind()
    WorldFact.__table__.create(connection, checkfirst=True)
    columns = {c["name"] for c in sa.inspect(connection).get_columns("character_memories")}
    if "world_fact_id" not in columns:
        # SQLite 支持新增可空 REFERENCES 列，无需重建已有记忆表。
        op.execute("ALTER TABLE character_memories ADD COLUMN world_fact_id VARCHAR(32) REFERENCES world_facts(id) ON DELETE SET NULL")
        op.create_index("ix_character_memories_world_fact_id", "character_memories", ["world_fact_id"])
    if "perspective" not in columns:
        op.add_column("character_memories", sa.Column("perspective", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    raise RuntimeError("分层记忆不自动删表，请使用备份恢复。")
