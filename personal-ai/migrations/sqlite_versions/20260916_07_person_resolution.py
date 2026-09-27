"""可撤销、按文档隔离的人物身份确认。"""
from alembic import op

revision = "sqlite_20260916_07"
down_revision = "sqlite_20260916_06"
branch_labels = None
depends_on = None


def upgrade():
    from infrastructure.database import PersonResolution
    PersonResolution.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("人物身份确认不自动删除，请使用备份恢复。")
