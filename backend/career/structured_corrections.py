"""Version-bound user approval for changes to role analysis and positioning."""

from copy import deepcopy

from sqlalchemy import select

from career.db import Record
from career.models import Artifact
from career.schemas import ApplicationBrief, OpportunityBrief
from career.truth import owned, view

ALLOWED = {
    "OpportunityBrief": {"actual_outputs", "base_profession", "specialty", "tools", "main_skills",
                         "differentiators", "output_importance", "hiring_context"},
    "ApplicationBrief": {"positioning", "base_profession_identity", "main_skill_message", "differentiator_message",
                         "fatal_gaps", "selection_risks", "fatal_gap_strategy", "assignment_statement",
                         "do_not_position_as", "question_portfolio"},
}


def propose(service, workspace, artifact_id, old_fields, new_fields, reason):
    service.editable(service.ws(workspace))
    artifact = owned(service.db, Artifact, service.user, artifact_id)
    if artifact.workspace_id != workspace or artifact.kind not in ALLOWED or artifact.slot:
        raise ValueError("현재 직무 분석 또는 지원 전략을 선택해 주세요.")
    current = service.artifact(workspace, artifact.kind)
    if current.id != artifact.id:
        raise ValueError("현재 문서 버전으로 교정을 제안해 주세요.")
    if not new_fields or set(new_fields) != set(old_fields) or not set(new_fields) <= ALLOWED[artifact.kind]:
        raise ValueError("교정할 분석 항목과 정확한 수정 전후 값을 지정해 주세요.")
    if any(current.data.get(key) != old_fields[key] for key in new_fields):
        raise ValueError("교정 전 값이 현재 분석과 다릅니다.")
    schema = OpportunityBrief if artifact.kind == "OpportunityBrief" else ApplicationBrief
    preview = schema.model_validate({**current.data, **new_fields}).model_dump()
    if preview == current.data:
        raise ValueError("바뀐 분석 항목이 없습니다.")
    record = Record(user_id=service.user, kind="StructuredCorrectionProposal", data={
        "workspace_id": workspace, "artifact_id": current.id, "artifact_version": current.version,
        "artifact_kind": artifact.kind, "old_fields": deepcopy(old_fields), "new_fields": deepcopy(new_fields),
        "reason": reason, "status": "PENDING",
    })
    service.db.add(record)
    service.db.flush()
    return view(record)


def pending(service, workspace):
    service.ws(workspace)
    return [view(r) for r in service.db.scalars(select(Record).where(
        Record.user_id == service.user, Record.kind == "StructuredCorrectionProposal"
    ).order_by(Record.created_at)) if r.data.get("workspace_id") == workspace and r.data.get("status") == "PENDING"]


def apply(service, workspace, proposal_id, confirmed=False, reject=False):
    service.editable(service.ws(workspace))
    proposal = owned(service.db, Record, service.user, proposal_id)
    data = proposal.data
    if proposal.kind != "StructuredCorrectionProposal" or data["workspace_id"] != workspace:
        raise LookupError("교정 제안을 찾을 수 없습니다.")
    if data["status"] != "PENDING":
        return view(proposal)
    if reject:
        proposal.data = {**data, "status": "REJECTED"}
    else:
        if not confirmed:
            raise ValueError("교정할 항목의 수정 전후를 읽고 직접 승인해 주세요.")
        current = service.artifact(workspace, data["artifact_kind"])
        if current.id != data["artifact_id"] or current.version != data["artifact_version"]:
            raise ValueError("분석 버전이 바뀌었습니다. 새 버전에서 다시 제안해 주세요.")
        new_data = {**current.data, **data["new_fields"]}
        result = service.analyze(workspace, new_data) if current.kind == "OpportunityBrief" else service.strategy(workspace, new_data)
        proposal.data = {**data, "status": "ACCEPTED", "output_artifact_id": result.id}
    service.db.flush()
    return view(proposal)
