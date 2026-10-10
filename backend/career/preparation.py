"""Owner-scoped preparation context; historical feedback never becomes truth."""

from typing import TYPE_CHECKING

from sqlalchemy import select

from career.artifacts import fresh
from career.models import Artifact, Fact, Feedback, Source, Workspace
from career.projections import CorrectionRecord
from career.rules import writing_rules
from career.truth import canonical
from career.validation import GOOD

if TYPE_CHECKING:
    from career.workflow import Workflow


def preparation_context(service: "Workflow", workspace: Workspace, evidence: list[dict], question_type=""):
    db, user = service.db, service.user
    evidence_ids = {item["id"] for item in evidence}
    source_ids = {item["source_id"] for item in evidence}
    profile = canonical(db, user)
    rules = writing_rules(db, user, workspace, question_type, [item["title"] for item in evidence])
    sources = set()
    corrections = []
    for record in db.scalars(
        select(CorrectionRecord).where(CorrectionRecord.user_id == user).order_by(CorrectionRecord.created_at.desc())
    ):
        source = db.scalar(select(Source).where(Source.user_id == user, Source.id == record.source_id))
        if source is None or source.status not in GOOD:
            continue
        if record.fact_id:
            fact = db.scalar(select(Fact).where(Fact.user_id == user, Fact.id == record.fact_id))
            if fact is None or fact.status not in GOOD or fact.id not in {v["id"] for v in profile.values()}:
                continue
            payload = {"key": record.key, "fact_id": fact.id, "value": fact.value}
        elif record.evidence_id in evidence_ids or record.source_id in source_ids:
            payload = {"key": record.key, "evidence_id": record.evidence_id, "correction": record.data}
        else:
            continue
        corrections.append({"id": record.id, "source_id": record.source_id, **payload})
        sources.add(record.source_id)

    # Exact contextual scope, current versions only. Historical notes are visible
    # observations, never reusable rules or a permanent skill-gap judgement.
    relevant_workspaces = list(db.scalars(select(Workspace).where(
        Workspace.user_id == user,
        (Workspace.company == workspace.company) | (Workspace.role == workspace.role),
    )))
    workspace_ids = {item.id for item in relevant_workspaces if item.id != workspace.id}
    postmortems = []
    dependencies = set()
    for item in db.scalars(select(Artifact).where(
        Artifact.user_id == user, Artifact.workspace_id.in_(workspace_ids),
        Artifact.kind == "Postmortem", Artifact.status.in_(["ACTIVE", "LOCKED"]),
    ).order_by(Artifact.created_at.desc())):
        try:
            fresh(db, user, item)
        except (ValueError, LookupError):
            continue
        origin = next(w for w in relevant_workspaces if w.id == item.workspace_id)
        postmortems.append({
            "artifact_id": item.id, "version": item.version, "company": origin.company, "role": origin.role,
            "recorded_at": item.created_at.isoformat(), "attribution_scope": item.data.get("attribution_scope"),
            "observations": item.data.get("hypotheses", []), "user_notes": item.data.get("user_notes", ""),
            "authority": "HISTORICAL_WEAK_SIGNAL_NOT_CAUSE_OR_WRITING_RULE",
        })
        dependencies.add(item.id)
        if len(postmortems) == 5:
            break

    edits = []
    for event in db.scalars(select(Feedback).where(
        Feedback.user_id == user, Feedback.application_id == workspace.id, Feedback.action == "EDIT",
        Feedback.stage.in_(["EvidencePack", "ApplicationBrief", "QuestionBrief"]),
    ).order_by(Feedback.created_at.desc())):
        if event.data.get("edit_type") != "MANUAL_EDIT":
            continue
        artifact = db.scalar(select(Artifact).where(Artifact.user_id == user, Artifact.id == event.artifact_id))
        if artifact is None or artifact.status not in {"ACTIVE", "LOCKED"}:
            continue
        # Do not depend on the stage being replaced (which would stale its own
        # successor). Edits describe history; current artifacts remain authority.
        edits.append({"artifact_id": artifact.id, "stage": artifact.kind, "question_id": artifact.slot,
                      "version": artifact.version, "before": event.data.get("before"),
                      "after": event.data.get("after"), "authority": "USER_EDIT_HISTORY_NOT_NEW_FACT"})
        if len(edits) == 10:
            break
    return {
        "context": {"current_corrections": corrections, "current_workspace_edits": edits,
                    "previous_postmortems": postmortems, "verified_writing_guidance": rules,
                    "precedence": "CURRENT_CONFIRMED_TRUTH_THEN_CURRENT_USER_CORRECTION; HISTORY_IS_CONTEXT_ONLY"},
        "source_ids": sorted(sources), "guidance_source_ids": sorted({rule["source_id"] for rule in rules}),
        "depends_on": sorted(dependencies),
    }
