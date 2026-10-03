"""Persistent visible executions, scoped to their private workspace."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "execution_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("application_workspaces.id"), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("label", sa.String(150), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("active_key", sa.String(20), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint("user_id", "workspace_id", "active_key", name="uq_execution_active"),
    )
    op.create_index("ix_execution_runs_user_id", "execution_runs", ["user_id"])
    op.create_index("ix_execution_runs_workspace_id", "execution_runs", ["workspace_id"])


def downgrade():
    op.drop_table("execution_runs")
