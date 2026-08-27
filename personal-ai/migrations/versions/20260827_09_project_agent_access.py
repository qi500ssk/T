"""Allow projects to be shared with selected agent profiles.

Revision ID: 20260827_09
Revises: 20260827_08
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op


revision = "20260827_09"
down_revision = "20260827_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_agent_access" not in inspector.get_table_names():
        op.create_table(
            "project_agent_access",
            sa.Column("project_id", sa.String(length=32), nullable=False),
            sa.Column("agent_id", sa.String(length=100), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("project_id", "agent_id"),
        )
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("project_agent_access")
    }
    if "ix_project_agent_access_agent_id" not in indexes:
        op.create_index(
            "ix_project_agent_access_agent_id",
            "project_agent_access",
            ["agent_id"],
        )
    op.execute(
        """
        INSERT INTO project_agent_access (project_id, agent_id)
        SELECT id, 'default' FROM projects
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_agent_access_agent_id",
        table_name="project_agent_access",
    )
    op.drop_table("project_agent_access")
