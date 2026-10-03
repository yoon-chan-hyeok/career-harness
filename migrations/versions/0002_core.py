import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.create_table(
        "application_workspaces",
        sa.Column("company", sa.String(length=200), primary_key=False, nullable=False),
        sa.Column("role", sa.String(length=200), primary_key=False, nullable=False),
        sa.Column("jd_raw", sa.Text(), primary_key=False, nullable=False),
        sa.Column("state", sa.String(length=40), primary_key=False, nullable=False),
        sa.Column("mode", sa.String(length=20), primary_key=False, nullable=False),
        sa.Column("data", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_index("ix_application_workspaces_user_id", "application_workspaces", ["user_id"])
    op.create_table(
        "artifact_feedback_events",
        sa.Column("application_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("artifact_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("artifact_version", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("stage", sa.String(length=60), primary_key=False, nullable=False),
        sa.Column("action", sa.String(length=20), primary_key=False, nullable=False),
        sa.Column("data", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_index(
        "ix_artifact_feedback_events_application_id", "artifact_feedback_events", ["application_id"]
    )
    op.create_index("ix_artifact_feedback_events_user_id", "artifact_feedback_events", ["user_id"])
    op.create_table(
        "artifacts",
        sa.Column("workspace_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("kind", sa.String(length=50), primary_key=False, nullable=False),
        sa.Column("slot", sa.String(length=100), primary_key=False, nullable=False),
        sa.Column("version", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("status", sa.String(length=30), primary_key=False, nullable=False),
        sa.Column("depends_on", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("source_ids", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("data", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("prompt_version", sa.String(length=50), primary_key=False, nullable=False),
        sa.Column("model_version", sa.String(length=100), primary_key=False, nullable=False),
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_index("ix_artifacts_user_id", "artifacts", ["user_id"])
    op.create_index("ix_artifacts_workspace_id", "artifacts", ["workspace_id"])
    op.create_table(
        "document_revision_events",
        sa.Column("application_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("document_type", sa.String(length=40), primary_key=False, nullable=False),
        sa.Column("from_version", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("to_version", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("data", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_index(
        "ix_document_revision_events_application_id", "document_revision_events", ["application_id"]
    )
    op.create_index("ix_document_revision_events_user_id", "document_revision_events", ["user_id"])
    op.create_table(
        "prompt_runs",
        sa.Column("stage", sa.String(length=60), primary_key=False, nullable=False),
        sa.Column("provider", sa.String(length=60), primary_key=False, nullable=False),
        sa.Column("data", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_index("ix_prompt_runs_user_id", "prompt_runs", ["user_id"])
    op.create_table(
        "sources",
        sa.Column("path", sa.Text(), primary_key=False, nullable=False),
        sa.Column("content_hash", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("authority", sa.String(length=40), primary_key=False, nullable=False),
        sa.Column("status", sa.String(length=30), primary_key=False, nullable=False),
        sa.Column("data", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
        sa.UniqueConstraint("user_id", "path", "content_hash"),
    )
    op.create_index("ix_sources_user_id", "sources", ["user_id"])
    op.create_table(
        "career_facts",
        sa.Column("key", sa.String(length=200), primary_key=False, nullable=False),
        sa.Column("fact_type", sa.String(length=40), primary_key=False, nullable=False),
        sa.Column("value", sa.JSON(), primary_key=False, nullable=False),
        sa.Column(
            "source_id", sa.String(length=64), sa.ForeignKey("sources.id"), primary_key=False, nullable=False
        ),
        sa.Column("status", sa.String(length=30), primary_key=False, nullable=False),
        sa.Column("supersedes_id", sa.String(length=64), primary_key=False, nullable=True),
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_index("ix_career_facts_user_id", "career_facts", ["user_id"])
    op.create_index("ix_career_facts_key", "career_facts", ["key"])
    op.create_table(
        "evidences",
        sa.Column(
            "source_id", sa.String(length=64), sa.ForeignKey("sources.id"), primary_key=False, nullable=False
        ),
        sa.Column("title", sa.Text(), primary_key=False, nullable=False),
        sa.Column("body", sa.Text(), primary_key=False, nullable=False),
        sa.Column("kind", sa.String(length=40), primary_key=False, nullable=False),
        sa.Column("status", sa.String(length=30), primary_key=False, nullable=False),
        sa.Column("data", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False),
    )
    op.create_index("ix_evidences_user_id", "evidences", ["user_id"])


def downgrade():
    op.drop_table("evidences")
    op.drop_table("career_facts")
    op.drop_table("sources")
    op.drop_table("prompt_runs")
    op.drop_table("document_revision_events")
    op.drop_table("artifacts")
    op.drop_table("artifact_feedback_events")
    op.drop_table("application_workspaces")
