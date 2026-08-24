"""Allow local embedding model paths in memory version metadata.

Revision ID: 20260824_07
Revises: 20260824_06
Create Date: 2026-08-24
"""

import sqlalchemy as sa
from alembic import op


revision = "20260824_07"
down_revision = "20260824_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "memories",
        "embedding_version",
        existing_type=sa.String(length=40),
        type_=sa.String(length=255),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "memories",
        "embedding_version",
        existing_type=sa.String(length=255),
        type_=sa.String(length=40),
        existing_nullable=True,
    )
