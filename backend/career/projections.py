"""Relational read models derived from canonical workspaces and versioned artifacts."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from career.db import Base, Owned


class ApplicationRow(Owned, Base):
    __abstract__ = True
    workspace_id: Mapped[str] = mapped_column(ForeignKey("application_workspaces.id"), index=True)


class ArtifactRow(ApplicationRow):
    __abstract__ = True
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)


class Opportunity(ApplicationRow):
    __tablename__ = "opportunities"
    company: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(200))
    jd_raw: Mapped[str] = mapped_column(Text)


class ApplicationQuestion(ApplicationRow):
    __tablename__ = "application_questions"
    text: Mapped[str] = mapped_column(Text)
    character_limit: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(40), index=True)


class JobOutput(ArtifactRow):
    __tablename__ = "opportunity_job_outputs"
    output: Mapped[str] = mapped_column(Text)


class EvidenceMap(ArtifactRow):
    __tablename__ = "opportunity_evidence_maps"
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidences.id"), index=True)
    output: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class ArtifactDependency(ArtifactRow):
    __tablename__ = "artifact_dependencies"
    prerequisite_id: Mapped[str] = mapped_column(String(64), index=True)
    prerequisite_type: Mapped[str] = mapped_column(String(20))


class DraftVersion(ArtifactRow):
    __tablename__ = "draft_versions"
    question_id: Mapped[str | None] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    protected_spans: Mapped[list[str]] = mapped_column(JSON)


class CompanyResearch(ArtifactRow):
    __tablename__ = "company_research_results"
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class ReviewIssue(ArtifactRow):
    __tablename__ = "review_issues"
    priority: Mapped[str] = mapped_column(String(10))
    code: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)


class SubmissionSnapshot(ArtifactRow):
    __tablename__ = "submission_snapshots"
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON)


class InterviewHandoff(ArtifactRow):
    __tablename__ = "interview_handoff_records"
    submission_bundle_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)


class SelectionOutcome(ApplicationRow):
    __tablename__ = "selection_outcomes"
    stage: Mapped[str] = mapped_column(String(40))
    result: Mapped[str] = mapped_column(String(40))
    notes: Mapped[str] = mapped_column(Text)


class PostmortemHypothesis(ArtifactRow):
    __tablename__ = "postmortem_hypotheses"
    observation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(20))
    attribution_scope: Mapped[str] = mapped_column(String(40))


class CorrectionRecord(Owned, Base):
    __tablename__ = "correction_records"
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    fact_id: Mapped[str | None] = mapped_column(ForeignKey("career_facts.id"), index=True)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidences.id"), index=True)
    key: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


APPLICATION_MODELS = [
    Opportunity,
    ApplicationQuestion,
    JobOutput,
    EvidenceMap,
    ArtifactDependency,
    DraftVersion,
    CompanyResearch,
    ReviewIssue,
    SubmissionSnapshot,
    InterviewHandoff,
    SelectionOutcome,
    PostmortemHypothesis,
]


def sync_workspace(db: Session, ws):
    opportunity = db.get(Opportunity, ws.id)
    if opportunity is None:
        db.add(
            Opportunity(
                id=ws.id,
                user_id=ws.user_id,
                workspace_id=ws.id,
                company=ws.company,
                role=ws.role,
                jd_raw=ws.jd_raw,
            )
        )
    for q in ws.data.get("questions", []):
        item = db.get(ApplicationQuestion, q["id"])
        state = ws.data.get("question_states", {}).get(q["id"], "CREATED")
        if item is None:
            item = ApplicationQuestion(
                id=q["id"],
                user_id=ws.user_id,
                workspace_id=ws.id,
                text=q["text"],
                character_limit=q["limit"],
                state=state,
            )
            db.add(item)
        else:
            item.state = state


def project_artifact(db: Session, artifact):
    common = dict(user_id=artifact.user_id, workspace_id=artifact.workspace_id, artifact_id=artifact.id)
    for kind, identifiers in [("ARTIFACT", artifact.depends_on), ("SOURCE", artifact.source_ids)]:
        db.add_all(
            [
                ArtifactDependency(**common, prerequisite_id=ident, prerequisite_type=kind)
                for ident in identifiers
            ]
        )
    data = artifact.data
    if artifact.kind == "OpportunityBrief":
        db.add_all([JobOutput(**common, output=output) for output in data["actual_outputs"]])
    elif artifact.kind == "EvidencePack":
        db.add_all(
            [
                EvidenceMap(
                    **common,
                    evidence_id=item["evidence_id"],
                    output=item["job_output_id"],
                    classification=item["classification"],
                    data=item,
                )
                for item in data["items"]
            ]
        )
    elif artifact.kind in {"Draft", "ResumeContent"}:
        db.add(
            DraftVersion(
                **common,
                question_id=artifact.slot or None,
                version=artifact.version,
                content=data["text"],
                protected_spans=data.get("protected_spans", []),
            )
        )
    elif artifact.kind == "CompanyResearchResult":
        db.add(CompanyResearch(**common, data=data))
    elif artifact.kind in {"Review", "ResumeReview", "PortfolioReview"}:
        db.add_all(
            [
                ReviewIssue(**common, **{k: issue[k] for k in ["priority", "code", "message"]})
                for issue in data["issues"]
            ]
        )
    elif artifact.kind == "SubmissionBundle":
        db.add(
            SubmissionSnapshot(
                **common, frozen_at=datetime.fromisoformat(data["frozen_at"]), submitted_at=None, content=data
            )
        )
    elif artifact.kind == "InterviewHandoff":
        db.add(InterviewHandoff(**common, submission_bundle_id=data["submission_bundle_id"], content=data))
    elif artifact.kind == "Postmortem":
        db.add(
            PostmortemHypothesis(
                **common,
                observation=data["observation"],
                confidence=data["confidence"],
                attribution_scope=data["attribution_scope"],
            )
        )
