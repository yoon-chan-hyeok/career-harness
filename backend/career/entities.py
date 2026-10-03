"""Dedicated, versioned truth tables with shared provenance columns."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from career.db import Base, Owned


class TruthEntity(Owned, Base):
    __abstract__ = True
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), index=True)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidences.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="UNVERIFIED", index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class ProjectRecord(TruthEntity):
    __tablename__ = "projects"


class DecisionEpisodeRecord(TruthEntity):
    __tablename__ = "decision_episodes"


class MetricRecord(TruthEntity):
    __tablename__ = "metrics"


class OwnershipRecord(TruthEntity):
    __tablename__ = "ownership_records"


class ClaimBoundaryRecord(TruthEntity):
    __tablename__ = "claim_boundaries"


class WritingRuleRecord(TruthEntity):
    __tablename__ = "writing_rules"


class ExpressionRecord(TruthEntity):
    __tablename__ = "expression_records"


class CapabilityRecord(TruthEntity):
    __tablename__ = "capability_records"


ENTITY_MODELS = dict(
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
            ProjectRecord,
            DecisionEpisodeRecord,
            MetricRecord,
            OwnershipRecord,
            ClaimBoundaryRecord,
            WritingRuleRecord,
            ExpressionRecord,
            CapabilityRecord,
        ],
        strict=True,
    )
)
