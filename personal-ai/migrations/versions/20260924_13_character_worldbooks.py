"""Restore PostgreSQL support for character memories and worldbooks."""
from alembic import op
import sqlalchemy as sa

revision = "20260924_13"
down_revision = "20260911_12"
branch_labels = None
depends_on = None


def upgrade():
    from infrastructure.database import Base
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # Different embedding models can use different dimensions. Their version
    # filters precede exact pgvector recall; fixed-dimension legacy indexes cannot
    # safely index all versions. Stored embeddings are not regenerated or lost.
    for table in ("memories", "document_chunks"):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_embedding_hnsw")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector USING embedding::vector")
    for table, column in (
        ("documents", sa.Column("agent_id", sa.String(100), nullable=True)),
        ("messages", sa.Column("thinking", sa.Text(), nullable=True)),
    ):
        if column.name not in {c['name'] for c in sa.inspect(bind).get_columns(table)}:
            op.add_column(table, column)
    # Newly introduced tables are created in foreign-key dependency order.
    Base.metadata.create_all(bind=bind, checkfirst=True)
    op.alter_column("document_chunks", "embedding", nullable=True)
    for index in Base.metadata.tables['documents'].indexes:
        index.create(bind, checkfirst=True)


def downgrade():
    raise RuntimeError("请从备份恢复，不自动删除角色记忆或世界书")
