from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from career.models import Artifact, Fact, Source, Workspace
from career.telemetry import feedback, revision
from career.truth import owned
from career.validation import GOOD


def latest(db: Session, user: str, workspace: str, kind: str, slot="", required=True) -> Artifact | None:
    row = db.scalar(
        select(Artifact)
        .where(
            Artifact.user_id == user,
            Artifact.workspace_id == workspace,
            Artifact.kind == kind,
            Artifact.slot == slot,
        )
        .order_by(Artifact.version.desc())
    )
    if row is None and required:
        raise ValueError(f"{kind} 단계가 필요합니다.")
    return row


def fresh(db: Session, user: str, artifact: Artifact, seen=None):
    if artifact.user_id != user or artifact.status not in {"ACTIVE", "LOCKED"}:
        raise ValueError("이전 근거로 작성된 결과입니다. 다시 검토해 주세요.")
    seen = set() if seen is None else seen
    if artifact.id in seen:
        return
    seen.add(artifact.id)
    for source_id in artifact.source_ids:
        if owned(db, Source, user, source_id).status not in GOOD:
            raise ValueError("출처가 무효화되었습니다.")
    for claim in artifact.data.get("claims", []):
        for fact_id in claim.get("profile_fact_ids", []):
            fact = owned(db, Fact, user, fact_id)
            if fact.status not in GOOD or owned(db, Source, user, fact.source_id).status not in GOOD:
                raise ValueError("문서가 참조한 프로필 사실이 변경되거나 충돌했습니다. 다시 검토해 주세요.")
    for ident in artifact.depends_on:
        fresh(db, user, owned(db, Artifact, user, ident), seen)


def stale(db: Session, user: str, identifiers: list[str]):
    pending = set(identifiers)
    changed = []
    all_artifacts = list(db.scalars(select(Artifact).where(Artifact.user_id == user)))
    while pending:
        batch, pending = pending, set()
        for artifact in all_artifacts:
            if artifact.kind == "SubmissionBundle" or artifact.status in {"STALE", "SUPERSEDED", "INVALID"}:
                continue
            historical_sources = (
                artifact.data.get("historical_source_ids", []) if artifact.kind == "InterviewHandoff" else []
            )
            if batch.intersection(artifact.depends_on + artifact.source_ids + historical_sources):
                artifact.status = "STALE"
                changed.append(artifact.id)
                pending.add(artifact.id)
                workspace = db.scalar(
                    select(Workspace).where(Workspace.id == artifact.workspace_id, Workspace.user_id == user)
                )
                if workspace and workspace.state not in {"SUBMISSION_FROZEN", "SUBMITTED", "CLOSED"}:
                    workspace.state = "NEED_USER_ACTION"
                    if artifact.slot:
                        workspace.data = {
                            **workspace.data,
                            "question_states": {
                                **workspace.data.get("question_states", {}),
                                artifact.slot: "STALE",
                            },
                        }
                    if artifact.kind.startswith("Resume"):
                        workspace.data = {**workspace.data, "resume_state": "STALE"}
                    from career.projections import sync_workspace

                    sync_workspace(db, workspace)
    return changed


def save(
    db: Session,
    user: str,
    workspace: str,
    kind: str,
    data: dict,
    deps=None,
    sources=None,
    slot="",
    model="manual",
):
    old = latest(db, user, workspace, kind, slot, required=False)
    if old and kind == "SubmissionBundle":
        raise ValueError("제출 보관본은 변경할 수 없습니다. 새 지원 작업을 만드세요.")
    changed = []
    if old:
        changed = stale(db, user, [old.id])
        old.status = "SUPERSEDED"
    item = Artifact(
        user_id=user,
        workspace_id=workspace,
        kind=kind,
        slot=slot,
        version=old.version + 1 if old else 1,
        data=deepcopy(data),
        depends_on=deps or [],
        source_ids=sources or [],
        model_version=model,
        prompt_version="v2-supplement"
        if any(owned(db, Source, user, s).authority == "REFERENCE" for s in sources or [])
        else "v1",
    )
    db.add(item)
    db.flush()
    from career.projections import project_artifact

    project_artifact(db, item)
    from career.activity import bind_output

    bind_output(db, user, workspace, item)
    if old and kind in {"Draft", "ResumeContent"}:
        revision(db, user, old, item)
    elif old and kind in {"EvidencePack", "ApplicationBrief", "QuestionBrief"}:
        event = feedback(db, user, item, "EDIT", old.data, data)
        event.data = {**event.data, "edit_type": "MANUAL_EDIT" if model == "manual" else "MODEL_REGENERATION"}
    return item, changed


def lock(db: Session, user: str, artifact: Artifact):
    fresh(db, user, artifact)
    artifact.status = "LOCKED"
