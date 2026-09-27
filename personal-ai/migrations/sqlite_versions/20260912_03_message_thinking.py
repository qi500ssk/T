"""消息新增 thinking 列：保存角色回答前的内心独白；保留既有数据。"""
from alembic import op
import sqlalchemy as sa

revision = "sqlite_20260912_03"
down_revision = "sqlite_20260912_02"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # 新库由基线 create_all 建出该列；旧库明确增量升级。
    columns = {column["name"] for column in sa.inspect(connection).get_columns("messages")}
    if "thinking" not in columns:
        op.add_column("messages", sa.Column("thinking", sa.Text(), nullable=True))


def downgrade():
    raise RuntimeError("消息独白列不自动删除；请使用备份恢复。")
