"""Repair installations stamped before the candidate table was added to revision 10."""
from alembic import op

revision = "sqlite_20260924_11"
down_revision = "sqlite_20260923_10"
branch_labels = None
depends_on = None


def upgrade():
    from infrastructure.database import CandidateMemory, CharacterStoryBinding
    CharacterStoryBinding.__table__.create(op.get_bind(), checkfirst=True)
    CandidateMemory.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    # These tables also belong to revision 10; never remove user memories.
    pass
