"""Initialize PostgreSQL schema with pgvector storage.

Revision ID: 20260823_01
Revises:
Create Date: 2026-08-23
"""

from alembic import op

from infrastructure.database import Base


revision = "20260823_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=bind)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memories_embedding_hnsw "
        "ON memories USING hnsw (embedding vector_cosine_ops) "
        "WHERE embedding IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memories_user_active_kind "
        "ON memories (user_id, is_active, kind)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_user_status "
        "ON documents (user_id, status)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
