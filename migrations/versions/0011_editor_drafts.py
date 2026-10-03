"""Private account-scoped recoverable input; approval is never stored here."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "editor_drafts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("workspace_id", sa.String(64), nullable=True),
        sa.Column("base_artifact_id", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "key", name="uq_editor_draft_key"),
    )
    op.create_index("ix_editor_drafts_user_id", "editor_drafts", ["user_id"])
    op.create_index("ix_editor_drafts_workspace_id", "editor_drafts", ["workspace_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE editor_drafts ENABLE ROW LEVEL SECURITY")
        op.execute("REVOKE ALL ON TABLE editor_drafts FROM PUBLIC")
        op.execute("""DO $$ DECLARE role_name text; BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
                IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE editor_drafts FROM %I', role_name);
                END IF;
            END LOOP;
        END $$""")


def downgrade():
    op.drop_table("editor_drafts")
