"""Single administrator and revocable login sessions."""

from alembic import op
import sqlalchemy as sa

# 历史迁移固定结构，不再依赖已移除的账号运行时模型。
metadata = sa.MetaData()
accounts = sa.Table("admin_accounts", metadata,
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("username", sa.String(80), nullable=False, unique=True),
    sa.Column("password_hash", sa.String(300), nullable=False),
    sa.CheckConstraint("id = 1", name="ck_single_admin"))
sessions = sa.Table("login_sessions", metadata,
    sa.Column("token_hash", sa.String(64), primary_key=True),
    sa.Column("account_id", sa.ForeignKey("admin_accounts.id", ondelete="CASCADE"), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True))

revision = "20260911_11"
down_revision = "20260827_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    sessions.drop(op.get_bind())
    accounts.drop(op.get_bind())
