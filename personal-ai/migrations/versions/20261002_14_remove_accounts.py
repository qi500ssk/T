"""取消本机账号，保留全部聊天、记忆、资料和任务数据。"""
from alembic import op

revision = "20261002_14"
down_revision = "20260924_13"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("recovery_codes", "login_sessions", "admin_accounts"):
        op.execute(f"DROP TABLE IF EXISTS {table}")


def downgrade():
    raise RuntimeError("账号功能已移除；如需回退，请使用升级前的数据库备份")
