"""Persist story identity independently of memory deletion."""
from alembic import op
revision = "sqlite_20260923_10"
down_revision = "sqlite_20260922_09"
branch_labels = None
depends_on = None

def upgrade():
    from infrastructure.database import CharacterStoryBinding, CandidateMemory
    CharacterStoryBinding.__table__.create(op.get_bind(), checkfirst=True)
    CandidateMemory.__table__.create(op.get_bind(), checkfirst=True)

def downgrade():
    raise RuntimeError("请使用备份恢复角色身份")
