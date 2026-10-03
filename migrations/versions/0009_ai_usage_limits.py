"""Durable private AI limits and conservative request reservations."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("ai_usage_settings", "ai_usage_buckets", "ai_usage_reservations"):
        columns = [
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
        ]
        if table == "ai_usage_settings":
            columns.append(sa.UniqueConstraint("user_id", name="uq_ai_usage_settings_user"))
        elif table == "ai_usage_buckets":
            columns.extend([
                sa.Column("period", sa.String(16), nullable=False),
                sa.UniqueConstraint("user_id", "period", name="uq_ai_usage_bucket_period"),
            ])
        else:
            columns.append(sa.Column("status", sa.String(20), nullable=False))
        op.create_table(table, *columns)
        op.create_index("ix_" + table + "_user_id", table, ["user_id"])
        if op.get_bind().dialect.name == "postgresql":
            # The backend enforces ownership; these ledgers are never exposed
            # directly through Supabase's anon/authenticated Data API roles.
            op.execute("ALTER TABLE " + table + " ENABLE ROW LEVEL SECURITY")
            op.execute("REVOKE ALL ON TABLE " + table + " FROM PUBLIC")
            op.execute("""DO $$ DECLARE role_name text; BEGIN
                FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
                    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
                        EXECUTE format('REVOKE ALL ON TABLE """ + table + """ FROM %I', role_name);
                    END IF;
                END LOOP;
            END $$""")


def downgrade():
    for table in ("ai_usage_reservations", "ai_usage_buckets", "ai_usage_settings"):
        op.drop_table(table)
