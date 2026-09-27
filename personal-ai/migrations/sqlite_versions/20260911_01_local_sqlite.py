"""SQLite 本地数据库基线；旧 PostgreSQL 迁移保留在 versions 作为历史。"""
from alembic import op
from infrastructure.database import Base

revision = "sqlite_20260911_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(op.get_bind())


def downgrade():
    raise RuntimeError("本地数据不能自动清空；请使用数据库备份恢复")
