"""Move typed truth records into dedicated provenance-indexed tables."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"

TABLES = dict(
    zip(
        [
            "Project",
            "DecisionEpisode",
            "Metric",
            "Ownership",
            "ClaimBoundary",
            "WritingRule",
            "ExpressionRecord",
            "CapabilityRecord",
        ],
        [
            "projects",
            "decision_episodes",
            "metrics",
            "ownership_records",
            "claim_boundaries",
            "writing_rules",
            "expression_records",
            "capability_records",
        ],
        strict=True,
    )
)


def upgrade():
    for kind, name in TABLES.items():
        table = op.create_table(
            name,
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_id", sa.String(64), sa.ForeignKey("sources.id")),
            sa.Column("evidence_id", sa.String(64), sa.ForeignKey("evidences.id")),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
        )
        for column in ["user_id", "source_id", "evidence_id", "status"]:
            op.create_index(f"ix_{name}_{column}", name, [column])
        if op.get_context().as_sql:
            continue
        bind = op.get_bind()
        legacy = sa.table(
            "domain_records",
            sa.column("id", sa.String()),
            sa.column("user_id", sa.String()),
            sa.column("created_at", sa.DateTime()),
            sa.column("kind", sa.String()),
            sa.column("data", sa.JSON()),
        )
        for row in bind.execute(sa.select(legacy).where(legacy.c.kind == kind)).mappings():
            data = row["data"]
            if isinstance(data, str):
                data = json.loads(data)
            # Raw importer records have original/line, not validated entity payloads.
            if "original" in data:
                continue
            bind.execute(
                table.insert().values(
                    id=row["id"],
                    user_id=row["user_id"],
                    created_at=row["created_at"],
                    source_id=data.get("source_id"),
                    evidence_id=data.get("evidence_id"),
                    version=data.get("version", 1),
                    status=data.get("status", "UNVERIFIED"),
                    data=data,
                )
            )
            bind.execute(legacy.delete().where(legacy.c.id == row["id"]))


def downgrade():
    bind = op.get_bind()
    for kind, name in reversed(list(TABLES.items())):
        if not op.get_context().as_sql:
            table = sa.Table(name, sa.MetaData(), autoload_with=bind)
            legacy = sa.Table("domain_records", sa.MetaData(), autoload_with=bind)
            for row in bind.execute(sa.select(table)).mappings():
                bind.execute(
                    legacy.insert().values(
                        id=row["id"],
                        user_id=row["user_id"],
                        created_at=row["created_at"],
                        kind=kind,
                        data=row["data"],
                    )
                )
        op.drop_table(name)
