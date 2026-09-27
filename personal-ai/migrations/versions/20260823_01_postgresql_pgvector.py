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
    # Current metadata supports multiple embedding dimensions; exact pgvector
    # recall is filtered by model/dimension. Old fixed-dimension HNSW indexes
    # are removed by revision 13 when upgrading an existing database.
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
