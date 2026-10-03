from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from career.db import now
from career.models import Artifact, Feedback, Revision


def feedback(db: Session, user: str, artifact: Artifact, action: str, before=None, after=None):
    if artifact.user_id != user or action not in {"ACCEPT", "EDIT", "REJECT", "SKIP"}:
        raise ValueError("Invalid feedback")
    event = Feedback(
        user_id=user,
        application_id=artifact.workspace_id,
        artifact_id=artifact.id,
        artifact_version=artifact.version,
        stage=artifact.kind,
        action=action,
        data={
            "before": before,
            "after": after,
            "question_id": artifact.slot or None,
            "edit_type": "USER_EDIT" if action == "EDIT" else None,
        },
    )
    if action == "ACCEPT" and artifact.kind in {"Draft", "ResumeContent"}:
        first = db.scalar(
            select(Artifact)
            .where(
                Artifact.user_id == user,
                Artifact.workspace_id == artifact.workspace_id,
                Artifact.kind == artifact.kind,
                Artifact.slot == artifact.slot,
            )
            .order_by(Artifact.version)
        )
        if first is not None:
            event.data = {
                **event.data,
                "final_user_edit_distance": 1
                - SequenceMatcher(None, first.data["text"], artifact.data["text"]).ratio(),
                "first_draft_accepted": first.id == artifact.id,
                "seconds_to_final": (
                    now().replace(tzinfo=None) - first.created_at.replace(tzinfo=None)
                ).total_seconds(),
            }
    db.add(event)
    return event


def revision(db: Session, user: str, old: Artifact, new: Artifact):
    before, after = str(old.data.get("text", "")), str(new.data.get("text", ""))
    review = db.scalar(
        select(Artifact)
        .where(
            Artifact.user_id == user,
            Artifact.workspace_id == old.workspace_id,
            Artifact.kind == ("ResumeReview" if old.kind == "ResumeContent" else "Review"),
            Artifact.slot == old.slot,
        )
        .order_by(Artifact.version.desc())
    )
    db.add(
        Revision(
            user_id=user,
            application_id=old.workspace_id,
            document_type=old.kind,
            from_version=old.version,
            to_version=new.version,
            data={
                "edit_distance_ratio": 1 - SequenceMatcher(None, before, after).ratio(),
                "before_artifact": old.id,
                "after_artifact": new.id,
                "reviewer_issue_ids": [i["code"] for i in review.data.get("issues", [])]
                if review and old.id in review.depends_on
                else [],
                "diff_summary": {"before_characters": len(before), "after_characters": len(after)},
            },
        )
    )


def export_events(db: Session, user: str):
    return [
        {
            "stage": e.stage,
            "action": e.action,
            "artifact_id": e.artifact_id,
            "artifact_version": e.artifact_version,
            **e.data,
        }
        for e in db.scalars(select(Feedback).where(Feedback.user_id == user))
    ]
