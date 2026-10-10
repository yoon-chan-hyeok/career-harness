"""Shared request limits for the public service."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("request_rate_buckets",
                    sa.Column("user_id", sa.String(64), primary_key=True),
                    sa.Column("minute", sa.Integer(), nullable=False),
                    sa.Column("requests", sa.Integer(), nullable=False),
                    sa.Column("mutations", sa.Integer(), nullable=False))
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE request_rate_buckets ENABLE ROW LEVEL SECURITY")
        op.execute("REVOKE ALL ON TABLE request_rate_buckets FROM PUBLIC")
        op.execute("""DO $$ DECLARE role_name text; BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
                IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE request_rate_buckets FROM %I', role_name);
                END IF;
            END LOOP;
        END $$""")


def downgrade():
    op.drop_table("request_rate_buckets")
