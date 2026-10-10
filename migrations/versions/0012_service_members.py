"""Operator-managed invite access and per-user ceilings."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("service_members",
                    sa.Column("user_id", sa.String(64), primary_key=True),
                    sa.Column("status", sa.String(20), nullable=False),
                    sa.Column("limits", sa.JSON(), nullable=False),
                    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE service_members ENABLE ROW LEVEL SECURITY")
        op.execute("REVOKE ALL ON TABLE service_members FROM PUBLIC")
        op.execute("""DO $$ DECLARE role_name text; BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
                IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE service_members FROM %I', role_name);
                END IF;
            END LOOP;
        END $$""")


def downgrade():
    op.drop_table("service_members")
