"""Offline one-time recovery codes for the local account."""

from alembic import op
from infrastructure.database import RecoveryCode

revision = "20260911_12"
down_revision = "20260911_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    RecoveryCode.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    RecoveryCode.__table__.drop(op.get_bind())
