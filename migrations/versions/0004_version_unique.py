from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade():
    with op.batch_alter_table("artifacts") as batch:
        batch.create_unique_constraint(
            "uq_artifact_version", ["user_id", "workspace_id", "kind", "slot", "version"]
        )


def downgrade():
    with op.batch_alter_table("artifacts") as batch:
        batch.drop_constraint("uq_artifact_version", type_="unique")
