"""Evidence correction provenance without requiring a profile fact."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("correction_records") as batch:
        batch.alter_column("fact_id", existing_type=sa.String(64), nullable=True)
        batch.add_column(sa.Column("evidence_id", sa.String(64), nullable=True))
        batch.create_foreign_key("fk_correction_evidence", "evidences", ["evidence_id"], ["id"])
        batch.create_index("ix_correction_records_evidence_id", ["evidence_id"])
    metadata = sa.MetaData()
    metadata.reflect(bind=op.get_bind())
    records = metadata.tables["domain_records"]
    corrections = metadata.tables["correction_records"]
    evidences = metadata.tables["evidences"]
    for r in op.get_bind().execute(sa.select(records).where(records.c.kind == "Correction")).mappings():
        evidence = (
            op.get_bind()
            .execute(
                sa.select(evidences).where(
                    evidences.c.id == r["data"].get("evidence_id"), evidences.c.user_id == r["user_id"]
                )
            )
            .mappings()
            .first()
        )
        if evidence:
            op.get_bind().execute(
                corrections.insert().values(
                    id=str(uuid4()),
                    user_id=r["user_id"],
                    created_at=r["created_at"],
                    source_id=evidence["source_id"],
                    evidence_id=evidence["id"],
                    fact_id=None,
                    key=r["data"].get("command", "CORRECTION"),
                    data=r["data"],
                )
            )


def downgrade():
    op.execute("DELETE FROM correction_records WHERE fact_id IS NULL")
    with op.batch_alter_table("correction_records") as batch:
        batch.drop_index("ix_correction_records_evidence_id")
        batch.drop_constraint("fk_correction_evidence", type_="foreignkey")
        batch.drop_column("evidence_id")
        batch.alter_column("fact_id", existing_type=sa.String(64), nullable=False)
