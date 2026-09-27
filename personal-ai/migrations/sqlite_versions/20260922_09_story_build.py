"""Persistent chapter-by-chapter worldbook generation."""
from alembic import op
revision = "sqlite_20260922_09"
down_revision = "sqlite_20260921_08"
branch_labels = None
depends_on = None

def upgrade():
    from infrastructure.database import StoryBuild
    StoryBuild.__table__.create(op.get_bind(), checkfirst=True)

def downgrade():
    raise RuntimeError("请使用备份恢复世界书生成记录")
