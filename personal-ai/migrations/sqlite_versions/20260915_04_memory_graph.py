"""增量保存记忆关系与时间信息，不改写既有记忆。"""
from alembic import op
import sqlalchemy as sa

revision = "sqlite_20260915_04"
down_revision = "sqlite_20260912_03"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("character_memories")}
    if "graph" not in columns:
        op.add_column("character_memories", sa.Column("graph", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    raise RuntimeError("记忆关系数据不自动删除，请从备份恢复。")
