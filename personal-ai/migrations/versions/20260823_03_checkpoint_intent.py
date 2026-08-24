"""Checkpoint recovery, ToolRun idempotency and persisted intent.

Revision ID: 20260823_03
Revises: 20260823_02
Create Date: 2026-08-23
"""

import sqlalchemy as sa
from alembic import op


revision = "20260823_03"
down_revision = "20260823_02"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _foreign_key_exists(table: str, column: str) -> bool:
    return any(
        column in (foreign_key.get("constrained_columns") or [])
        for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys(table)
    )


def upgrade() -> None:
    agent_columns = _columns("agent_runs")
    if "input_message_id" not in agent_columns:
        op.add_column("agent_runs", sa.Column("input_message_id", sa.String(32), nullable=True))
    if "intent_json" not in agent_columns:
        op.add_column("agent_runs", sa.Column("intent_json", sa.JSON(), nullable=True))
    if not _foreign_key_exists("agent_runs", "input_message_id"):
        op.create_foreign_key(
            "agent_runs_input_message_id_fkey",
            "agent_runs",
            "messages",
            ["input_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_runs_input_message_id "
        "ON agent_runs (input_message_id)"
    )

    tool_columns = _columns("tool_runs")
    if "plan_version" not in tool_columns:
        op.add_column("tool_runs", sa.Column("plan_version", sa.Integer(), nullable=True))
    if "plan_step_id" not in tool_columns:
        op.add_column("tool_runs", sa.Column("plan_step_id", sa.String(32), nullable=True))
    if "idempotency_key" not in tool_columns:
        op.add_column("tool_runs", sa.Column("idempotency_key", sa.String(64), nullable=True))
    if not _foreign_key_exists("tool_runs", "plan_step_id"):
        op.create_foreign_key(
            "tool_runs_plan_step_id_fkey",
            "tool_runs",
            "plan_steps",
            ["plan_step_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tool_runs_plan_step_id ON tool_runs (plan_step_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tool_runs_idempotency_key "
        "ON tool_runs (idempotency_key) WHERE idempotency_key IS NOT NULL"
    )

    if "checkpoints" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "checkpoints",
            sa.Column("id", sa.String(32), nullable=False),
            sa.Column("run_id", sa.String(32), nullable=False),
            sa.Column("plan_id", sa.String(32), nullable=False),
            sa.Column("step_id", sa.String(32), nullable=True),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("state_json", sa.JSON(), nullable=False),
            sa.Column("workspace_snapshot_json", sa.JSON(), nullable=False),
            sa.Column("capability_version", sa.String(64), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["step_id"], ["plan_steps.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "sequence", name="uq_checkpoint_run_sequence"),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_checkpoints_run_id ON checkpoints (run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_checkpoints_plan_id ON checkpoints (plan_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_checkpoints_step_id ON checkpoints (step_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_checkpoints_status ON checkpoints (status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_checkpoints_run_created "
        "ON checkpoints (run_id, created_at)"
    )


def downgrade() -> None:
    op.drop_table("checkpoints")
    op.execute("DROP INDEX IF EXISTS uq_tool_runs_idempotency_key")
    op.execute("DROP INDEX IF EXISTS ix_tool_runs_plan_step_id")
    op.drop_constraint("tool_runs_plan_step_id_fkey", "tool_runs", type_="foreignkey")
    op.drop_column("tool_runs", "idempotency_key")
    op.drop_column("tool_runs", "plan_step_id")
    op.drop_column("tool_runs", "plan_version")
    op.execute("DROP INDEX IF EXISTS ix_agent_runs_input_message_id")
    op.drop_constraint("agent_runs_input_message_id_fkey", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "intent_json")
    op.drop_column("agent_runs", "input_message_id")
