from copy import deepcopy

import pytest
from career.entities import OwnershipRecord
from career.models import Artifact, Source
from career.truth import add_evidence, register_source
from career.v3_preview import application_plan, experience_card
from career.workflow import Workflow
from sqlalchemy import event, select


@pytest.fixture
def sample(db):
    source, _ = register_source(db, "alice", "synthetic-results", "직접 실험 코드를 작성했습니다.", "RAW_RESULT")
    evidence = add_evidence(db, "alice", source.id, "합성 경험", "직접 실험 코드를 작성했습니다.",
                            {"ownership": {"implementation": "USER"}}, "VERIFIED")
    workspace = Workflow(db, "alice").create("합성회사", "분석가", "분석 보고서 작성")
    db.commit()
    return workspace, evidence, source


def artifact(db, workspace, kind, *, slot="", status="ACTIVE", data=None, deps=(), version=1):
    row = Artifact(user_id="alice", workspace_id=workspace.id, kind=kind, slot=slot,
                   status=status, data=data or {}, depends_on=list(deps), version=version)
    db.add(row)
    db.commit()
    return row


def node(plan, kind, slot=None):
    return next(n for n in plan.nodes if n.kind == kind and (slot is None or n.scope_id == slot))


def test_experience_without_a_job_reuses_existing_records_and_cannot_cross_owners(db, sample):
    _, evidence, source = sample
    record = OwnershipRecord(user_id="alice", source_id=source.id, evidence_id=evidence.id,
                             status="USER_CONFIRMED", data={"implementation": "USER"})
    db.add(record)
    db.commit()
    before = deepcopy(evidence.data)
    card = experience_card(db, "alice", evidence.id)
    assert card.records[0].id == record.id
    assert card.evidence.id == evidence.id and card.source.id == source.id
    assert card.mode == "READ_ONLY_PROJECTION" and not card.warnings
    assert evidence.data == before
    with pytest.raises(LookupError):
        experience_card(db, "bob", evidence.id)


def test_experience_revision_changes_on_ownership_and_related_source_corrections(db, sample):
    _, evidence, _ = sample
    extra, _ = register_source(db, "alice", "other-synthetic-source", "기여 범위", "RAW_RESULT")
    record = OwnershipRecord(user_id="alice", source_id=extra.id, evidence_id=evidence.id,
                             status="USER_CONFIRMED", data={"implementation": "USER"})
    db.add(record)
    db.commit()
    first = experience_card(db, "alice", evidence.id)
    record.status = "CONFLICTED"
    db.commit()
    second = experience_card(db, "alice", evidence.id)
    assert second.revision != first.revision and second.warnings
    extra.status = "INVALID"
    db.commit()
    third = experience_card(db, "alice", evidence.id)
    assert third.revision != second.revision and len(third.warnings) == 2


def test_reference_and_expression_never_become_fact_cards(db, sample):
    _, evidence, source = sample
    evidence.kind = "EXPRESSION"
    db.commit()
    with pytest.raises(ValueError):
        experience_card(db, "alice", evidence.id)
    evidence.kind = "EVIDENCE"
    source.authority = "REFERENCE"
    db.commit()
    with pytest.raises(ValueError):
        experience_card(db, "alice", evidence.id)


def test_reads_do_not_flush_write_or_call_workflow_or_models(db, sample, monkeypatch):
    workspace, evidence, _ = sample

    def forbidden(*args, **kwargs):
        pytest.fail("Preview attempted execution, mutation or a model call")

    def select_only(conn, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith("SELECT"), statement

    monkeypatch.setattr(Workflow, "command", forbidden)
    monkeypatch.setattr(Workflow, "ai", forbidden)
    monkeypatch.setattr(Workflow, "ready", forbidden)
    monkeypatch.setattr(Workflow, "freeze", forbidden)
    monkeypatch.setattr(Workflow, "confirm_submission", forbidden)
    event.listen(db.get_bind(), "before_cursor_execute", select_only)
    try:
        first = application_plan(db, "alice", workspace.id)
        assert application_plan(db, "alice", workspace.id) == first
        experience_card(db, "alice", evidence.id)
        assert not db.new and not db.dirty and not db.deleted
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", select_only)
    assert not first.can_execute and not first.completion_proof
    assert {n.budget_status for n in first.nodes} == {"NOT_REQUIRED", "NOT_ESTIMATED"}


def test_dirty_session_is_rejected_before_any_implicit_flush(db, sample):
    workspace, evidence, _ = sample
    evidence.body = "아직 저장하지 않은 변경"
    with pytest.raises(ValueError, match="저장"):
        application_plan(db, "alice", workspace.id)
    with pytest.raises(ValueError, match="저장"):
        experience_card(db, "alice", evidence.id)
    db.rollback()


def test_resume_only_and_three_question_scopes_are_distinct(db, sample):
    workspace, _, _ = sample
    workspace.data = {"questions": [{"id": f"q{i}"} for i in range(1, 4)]}
    db.commit()
    cover = application_plan(db, "alice", workspace.id)
    assert len([n for n in cover.nodes if n.kind == "CLAIM_APPROVAL"]) == 3
    assert len({n.id for n in cover.nodes}) == len(cover.nodes)
    allocation = node(cover, "PORTFOLIO_APPROVAL")
    assert all(allocation.id in n.depends_on for n in cover.nodes if n.kind == "CLAIM_PLAN")
    resume = application_plan(db, "alice", workspace.id, "RESUME_ONLY")
    assert node(resume, "COVER_COMPOSITION").status == "NOT_APPLICABLE"
    assert not any(n.kind == "CLAIM_PLAN" for n in resume.nodes)
    assert node(resume, "RESUME_LOCK").requires_human
    assert node(resume, "SUBMISSION_READINESS").status != "REUSE_CANDIDATE"
    assert resume.plan_id != cover.plan_id
    assert workspace.data["questions"] == [{"id": f"q{i}"} for i in range(1, 4)]


@pytest.mark.parametrize("status,expected", [("NOT_MET", "BLOCKED"), ("NEEDS_VERIFICATION", "WAITING_EVIDENCE")])
def test_eligibility_cannot_be_skipped_by_a_plan(db, sample, status, expected):
    workspace, _, _ = sample
    artifact(db, workspace, "OpportunityAssessment", data={"eligibility": [{"status": status}]})
    plan = application_plan(db, "alice", workspace.id, "RESUME_ONLY")
    assert node(plan, "ELIGIBILITY").status == expected
    assert node(plan, "STRATEGY").status == "PLANNED"


def test_failed_claim_and_review_remain_blocked(db, sample):
    workspace, _, _ = sample
    workspace.data = {"questions": [{"id": "q1"}]}
    db.commit()
    artifact(db, workspace, "ClaimEvidenceTest", slot="q1", data={"result": "NEEDS_REVISION"})
    artifact(db, workspace, "Review", slot="q1", data={"issues": [{"priority": "P0"}]})
    plan = application_plan(db, "alice", workspace.id)
    assert node(plan, "EVIDENCE_TEST").status == "BLOCKED"
    assert node(plan, "DOCUMENT_QA").status == "BLOCKED"
    assert node(plan, "DOCUMENT_LOCK").status == "PLANNED"


def test_passed_claim_record_for_a_different_brief_is_not_reused(db, sample):
    workspace, _, _ = sample
    workspace.data = {"questions": [{"id": "q1"}]}
    db.commit()
    artifact(db, workspace, "QuestionBrief", slot="q1", status="LOCKED")
    artifact(db, workspace, "ClaimEvidenceTest", slot="q1",
             data={"result": "PASSED", "brief_id": "old-brief", "brief_version": 1})
    assert node(application_plan(db, "alice", workspace.id), "EVIDENCE_TEST").status == "BLOCKED"


def test_unanswered_review_task_blocks_lock_plan(db, sample):
    workspace, _, _ = sample
    workspace.data = {"questions": [{"id": "q1"}]}
    db.commit()
    draft = artifact(db, workspace, "Draft", slot="q1")
    artifact(db, workspace, "Review", slot="q1", deps=[draft.id], data={
        "document_version": draft.version, "issues": [], "response_tasks": [{"id": "required-answer"}],
    })
    assert node(application_plan(db, "alice", workspace.id), "DOCUMENT_QA").status == "BLOCKED"


def test_explicit_human_hold_is_not_overridden_by_a_positive_assessment(db, sample):
    workspace, _, _ = sample
    assessment = artifact(db, workspace, "OpportunityAssessment", data={"recommendation": "PROCEED",
                                                                         "eligibility": [{"status": "MET"}]})
    workspace.data = {"opportunity_decision": {"artifact_id": assessment.id, "decision": "HOLD"}}
    db.commit()
    assert node(application_plan(db, "alice", workspace.id), "ELIGIBILITY").status == "BLOCKED"


def test_current_draft_does_not_override_a_stale_dependency(db, sample):
    workspace, _, _ = sample
    workspace.data = {"questions": [{"id": "q1"}]}
    db.commit()
    old = artifact(db, workspace, "QuestionBrief", slot="q1", status="STALE")
    artifact(db, workspace, "Draft", slot="q1", status="LOCKED", deps=[old.id])
    plan = application_plan(db, "alice", workspace.id)
    assert node(plan, "DRAFT").status == "STALE"
    assert node(plan, "DOCUMENT_LOCK").status == "STALE"


def test_no_submission_proof_is_inferred_and_interview_does_not_compose(db, sample):
    workspace, _, _ = sample
    before = application_plan(db, "alice", workspace.id, "INTERVIEW_ONLY")
    assert node(before, "SUBMISSION_SNAPSHOT").status == "WAITING_EVIDENCE"
    bundle = artifact(db, workspace, "SubmissionBundle", status="LOCKED", data={"submitted_at": None})
    workspace.state = "SUBMISSION_FROZEN"
    db.commit()
    snapshot = deepcopy(bundle.data)
    interview = application_plan(db, "alice", workspace.id, "INTERVIEW_ONLY")
    assert node(interview, "SUBMISSION_SNAPSHOT").status == "REUSE_CANDIDATE"
    assert node(interview, "DOCUMENT_COMPOSITION").status == "NOT_APPLICABLE"
    frozen = application_plan(db, "alice", workspace.id)
    assert node(frozen, "DOCUMENT_COMPOSITION").status == "BLOCKED"
    assert node(frozen, "SUBMISSION_CONFIRMATION").status == "WAITING_APPROVAL"
    assert workspace.state == "SUBMISSION_FROZEN" and bundle.data == snapshot


def test_cross_user_rows_never_appear_in_preview_and_revision_tracks_truth(db, sample):
    workspace, evidence, source = sample
    artifact(db, workspace, "EvidencePack", data={"items": [{"evidence_id": evidence.id}]})
    db.add(Artifact(user_id="bob", workspace_id=workspace.id, kind="ApplicationBrief",
                    status="LOCKED", data={"secret": "bob-private-marker"}))
    db.commit()
    first = application_plan(db, "alice", workspace.id)
    assert "bob-private-marker" not in first.model_dump_json()
    assert node(first, "STRATEGY").artifact is None
    with pytest.raises(LookupError):
        application_plan(db, "bob", workspace.id)
    evidence.status = "CONFLICTED"
    db.commit()
    second = application_plan(db, "alice", workspace.id)
    assert second.snapshot_revision != first.snapshot_revision
    assert second.plan_id != first.plan_id
    assert node(second, "EVIDENCE_MAPPING").status == "WAITING_EVIDENCE"
    assert node(second, "EVIDENCE_MAPPING").id == node(first, "EVIDENCE_MAPPING").id
    assert db.scalar(select(Source).where(Source.id == source.id)).status == source.status
