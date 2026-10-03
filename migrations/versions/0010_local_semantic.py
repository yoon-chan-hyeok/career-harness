"""Free device-side multilingual embeddings with model and content isolation."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "local_evidence_embeddings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "evidence_id", sa.String(64), sa.ForeignKey("evidences.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("profile_id", sa.String(100), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", sa.JSON().with_variant(Vector(384), "postgresql"), nullable=False),
        sa.UniqueConstraint("user_id", "evidence_id", "profile_id", name="uq_local_evidence_embedding"),
    )
    op.create_index("ix_local_evidence_embeddings_user_id", "local_evidence_embeddings", ["user_id"])
    op.create_index("ix_local_evidence_embeddings_evidence_id", "local_evidence_embeddings", ["evidence_id"])
    op.create_index("ix_local_evidence_embeddings_profile_id", "local_evidence_embeddings", ["profile_id"])
    if op.get_bind().dialect.name == "postgresql":
        # Exact cosine search is sufficient for a personal evidence store. It avoids
        # approximate-index recall losses while preserving native pgvector storage.
        op.execute("ALTER TABLE local_evidence_embeddings ENABLE ROW LEVEL SECURITY")
        op.execute("REVOKE ALL ON TABLE local_evidence_embeddings FROM PUBLIC")
        op.execute("""DO $$ DECLARE role_name text; BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
                IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE local_evidence_embeddings FROM %I', role_name);
                END IF;
            END LOOP;
        END $$""")


def downgrade():
    op.drop_table("local_evidence_embeddings")
