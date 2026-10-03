from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_evidence_fts ON evidences USING gin(to_tsvector('simple', title || ' ' || body))"
        )
        op.execute(
            "CREATE TABLE evidence_embeddings (evidence_id VARCHAR(64) PRIMARY KEY REFERENCES evidences(id) ON DELETE CASCADE, user_id VARCHAR(64) NOT NULL, embedding vector(1536) NOT NULL)"
        )
        op.execute("CREATE INDEX ix_embeddings_user ON evidence_embeddings(user_id)")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TABLE evidence_embeddings")
        op.execute("DROP INDEX ix_evidence_fts")
