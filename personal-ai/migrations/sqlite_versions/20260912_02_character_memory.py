"""好友背景记忆、提取任务和文档范围；保留既有 SQLite 数据。"""
from alembic import op
import sqlalchemy as sa

revision = "sqlite_20260912_02"
down_revision = "sqlite_20260911_01"
branch_labels = None
depends_on = None


def upgrade():
    from infrastructure.database import CharacterMemory, CharacterExtraction
    connection = op.get_bind()
    # 第一版基线按 metadata 建空库，新库可能已有这些列；旧库则明确增量升级。
    columns = {column["name"] for column in sa.inspect(connection).get_columns("documents")}
    if "agent_id" not in columns:
        op.add_column("documents", sa.Column("agent_id", sa.String(100), nullable=True))
        op.create_index("ix_documents_agent_id", "documents", ["agent_id"])
    for model in (CharacterExtraction, CharacterMemory):
        model.__table__.create(connection, checkfirst=True)


def downgrade():
    raise RuntimeError("角色记忆迁移不自动删表；请使用备份恢复。")
