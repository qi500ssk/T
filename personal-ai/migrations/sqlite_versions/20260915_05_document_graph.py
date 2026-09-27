"""文档全人物图谱，保留原有角色记忆。"""
from alembic import op

revision = "sqlite_20260915_05"
down_revision = "sqlite_20260915_04"
branch_labels = None
depends_on = None


def upgrade():
    from infrastructure.database import DocumentGraphChunk
    DocumentGraphChunk.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("图谱数据不自动删除，请从备份恢复。")
