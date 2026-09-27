"""可续跑、有证据的模型图谱整理。"""
from alembic import op
revision = "sqlite_20260921_08"
down_revision = "sqlite_20260916_07"
branch_labels = None
depends_on = None


def upgrade():
    from infrastructure.database import GraphOrganization
    GraphOrganization.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("请使用备份恢复，不自动删除整理记录。")
