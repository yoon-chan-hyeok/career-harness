"""Index source and submission references used by joins and account deletion."""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_career_facts_source_id", "career_facts", ["source_id"])
    op.create_index("ix_evidences_source_id", "evidences", ["source_id"])
    op.create_index(
        "ix_interview_handoff_records_submission_bundle_id",
        "interview_handoff_records",
        ["submission_bundle_id"],
    )


def downgrade():
    op.drop_index(
        "ix_interview_handoff_records_submission_bundle_id",
        table_name="interview_handoff_records",
    )
    op.drop_index("ix_evidences_source_id", table_name="evidences")
    op.drop_index("ix_career_facts_source_id", table_name="career_facts")
