"""Offline one-time recovery codes for the local account."""

from alembic import op
import sqlalchemy as sa

revision = "20260911_12"
down_revision = "20260911_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("recovery_codes"):
        op.create_table("recovery_codes",
            sa.Column("account_id", sa.Integer(), sa.ForeignKey("admin_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("code_hash", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_table("recovery_codes")
