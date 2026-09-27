"""Single administrator and revocable login sessions."""

from alembic import op
from infrastructure.database import AdminAccount, LoginSession

revision = "20260911_11"
down_revision = "20260827_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    AdminAccount.__table__.create(op.get_bind(), checkfirst=True)
    LoginSession.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    LoginSession.__table__.drop(op.get_bind())
    AdminAccount.__table__.drop(op.get_bind())
