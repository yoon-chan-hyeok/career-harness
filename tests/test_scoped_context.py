# ruff: noqa: F811 -- shared fixtures
from copy import deepcopy

import pytest
from career.entities import OwnershipRecord
from career.promotion import direct_preference
from career.scoped_context import ContextRequest, TaskType, compile_task_context
from career.truth import add_evidence, add_fact, register_source
from career.v3_preview import application_plan, experience_card
from career.workflow import Workflow
from pydantic import ValidationError
from sqlalchemy import event
from test_v3_preview import artifact, node, sample  # noqa: F401


def request(workspace, evidence, task: TaskType = "RESUME_WRITE", **changes):
    return ContextRequest(task_type=task, application_id=workspace.id,
                          required_evidence_ids=(evidence.id,), **changes)


def writing_ready(db, workspace, evidence):
    artifact(db, workspace, "EvidencePack", data={"items": [{"evidence_id": evidence.id, "classification": "DIRECT"}]})
    artifact(db, workspace, "ApplicationBrief", status="LOCKED", data={"positioning": "분석 결과 검증",
        "unrelated_private_field": "excluded-strategy-marker"})


def test_experience_review_without_job_does_not_promote_unverified_truth(db):
    source, _ = register_source(db, "alice", "new-experience", "아직 검증 전", "RAW_RESULT")
    evidence = add_evidence(db, "alice", source.id, "새 경험", "아직 검증 전")
    db.commit()
    result = compile_task_context(db, "alice", ContextRequest(task_type="EXPERIENCE_REVIEW",
                                  required_evidence_ids=(evidence.id,)))
    assert result.status == "INPUT_READY_OFFLINE"
    assert result.payload is not None
    assert result.payload["experiences"][0]["status"] == "UNVERIFIED"
    assert result.payload["experiences"][0]["warnings"]
    assert not result.can_execute and not result.completion_proof
    assert evidence.status == "UNVERIFIED"


@pytest.mark.parametrize("task", ["EXPERIENCE_REVIEW", "JOB_ASSESS", "QUESTION_PORTFOLIO", "COVER_WRITE", "RESUME_WRITE"])
def test_cross_user_evidence_context_and_linked_sources_are_denied(db, sample, task):
    workspace, evidence, source = sample
    kwargs = {"task_type": task, "required_evidence_ids": (evidence.id,)}
    if task != "EXPERIENCE_REVIEW":
        other_workspace = Workflow(db, "bob").create("본인 회사", "분석", "본인 공고")
        kwargs["application_id"] = other_workspace.id
    if task == "COVER_WRITE":
        question = Workflow(db, "bob").add_question(other_workspace.id, "역량", 600)
        kwargs["question_id"] = question["id"]
    db.commit()
    with pytest.raises(LookupError):
        compile_task_context(db, "bob", ContextRequest.model_validate(kwargs))
    with pytest.raises(LookupError):
        experience_card(db, "bob", evidence.id)
    with pytest.raises(LookupError):
        application_plan(db, "bob", workspace.id)
    foreign, _ = register_source(db, "bob", "foreign", "cross-user-private-marker", "RAW_RESULT")
    db.add(OwnershipRecord(user_id="alice", evidence_id=evidence.id, source_id=foreign.id,
                           status="USER_CONFIRMED", data={"private": "must-not-return"}))
    db.commit()
    with pytest.raises(LookupError):
        compile_task_context(db, "alice", ContextRequest(task_type="EXPERIENCE_REVIEW",
                              required_evidence_ids=(evidence.id,)))


def test_task_allowlist_and_current_scoped_preferences_are_distinct(db, sample):
    workspace, evidence, _ = sample
    writing_ready(db, workspace, evidence)
    direct_preference(db, "alice", "짧은 문장", confirmed=True)
    direct_preference(db, "alice", "회사 관련 선호", scope_type="COMPANY", scope_value=workspace.company, confirmed=True)
    direct_preference(db, "alice", "wrong-company-marker", scope_type="COMPANY", scope_value="다른회사", confirmed=True)
    direct_preference(db, "bob", "foreign-preference-marker", confirmed=True)
    db.commit()
    resume = compile_task_context(db, "alice", request(workspace, evidence))
    assert resume.status == "INPUT_READY_OFFLINE", resume.manifest.missing_information
    assert resume.payload is not None
    assert {p["rule"] for p in resume.payload["preferences"]} == {"짧은 문장", "회사 관련 선호"}
    assert "wrong-company-marker" not in resume.model_dump_json()
    assert "foreign-preference-marker" not in resume.model_dump_json()
    assert "excluded-strategy-marker" not in resume.model_dump_json()
    job = compile_task_context(db, "alice", ContextRequest(task_type="JOB_ASSESS", application_id=workspace.id))
    assert job.payload is not None
    assert job.payload["preferences"] == [] and job.payload["experiences"] == []
    assert "strategy" not in job.payload and "questions" not in job.payload
    assert job.manifest.revision != resume.manifest.revision
    portfolio = compile_task_context(db, "alice", request(workspace, evidence, "QUESTION_PORTFOLIO"))
    assert portfolio.status == "HOLD" and "CURRENT_QUESTIONS_REQUIRED" in portfolio.manifest.missing_information


def test_only_current_requested_canonical_facts_are_available_for_resume_or_assessment(db, sample):
    workspace, evidence, source = sample
    writing_ready(db, workspace, evidence)
    fact = add_fact(db, "alice", source.id, "profile", "education", {"text": "합성 교육"})
    other_source, _ = register_source(db, "alice", "other-profile", "범위 밖", "RAW_RESULT")
    add_fact(db, "alice", other_source.id, "profile", "other", {"text": "unselected-profile-marker"})
    db.commit()
    req = request(workspace, evidence, required_fact_ids=(fact.id,))
    result = compile_task_context(db, "alice", req)
    assert result.payload is not None
    assert [f["id"] for f in result.payload["profile_facts"]] == [fact.id]
    assert "unselected-profile-marker" not in result.model_dump_json()
    fact.status = "CONFLICTED"
    db.commit()
    held = compile_task_context(db, "alice", req)
    assert held.status == "HOLD" and held.payload is None
    with pytest.raises(ValidationError):
        request(workspace, evidence, "QUESTION_PORTFOLIO", required_fact_ids=(fact.id,))


def test_context_revisions_cover_truth_preferences_scope_and_current_question(db, sample):
    workspace, evidence, source = sample
    writing_ready(db, workspace, evidence)
    q = Workflow(db, "alice").add_question(workspace.id, "기술 역량을 설명하세요", 600)
    artifact(db, workspace, "QuestionBrief", slot=q["id"], data={"evidence_ids": [evidence.id]})
    req = request(workspace, evidence, "COVER_WRITE", question_id=q["id"])
    first = compile_task_context(db, "alice", req)
    assert first.status == "INPUT_READY_OFFLINE", first.manifest.missing_information
    assert first.payload is not None
    assert first.payload["question"]["text"] == q["text"]
    key = "EVIDENCE:" + evidence.id
    ref = next(r for r in first.manifest.references if r.kind == "EVIDENCE")
    pinned = req.model_copy(update={"expected_revisions": {key: ref.revision}})
    assert compile_task_context(db, "alice", pinned).status == "INPUT_READY_OFFLINE"
    evidence.body += " 최신 교정"
    db.commit()
    with pytest.raises(ValueError, match="버전"):
        compile_task_context(db, "alice", pinned)
    second = compile_task_context(db, "alice", req)
    assert second.manifest.revision != first.manifest.revision
    source.status = "DO_NOT_USE"
    db.commit()
    with pytest.raises(LookupError):
        compile_task_context(db, "alice", req)


@pytest.mark.parametrize("change", ["missing_pack", "unapproved_strategy", "unverified", "unknown_owner", "other_evidence"])
def test_missing_or_incompatible_required_material_holds_without_partial_payload(db, sample, change):
    workspace, evidence, _ = sample
    if change != "missing_pack":
        writing_ready(db, workspace, evidence)
    if change == "unapproved_strategy":
        artifact(db, workspace, "ApplicationBrief", status="ACTIVE", version=2)
    elif change == "unverified":
        evidence.status = "UNVERIFIED"
    elif change == "unknown_owner":
        evidence.data = {"ownership": {"implementation": "UNKNOWN"}}
    elif change == "other_evidence":
        artifact(db, workspace, "EvidencePack", version=2, data={"items": []})
    db.commit()
    result = compile_task_context(db, "alice", request(workspace, evidence))
    assert result.status == "HOLD" and result.payload is None
    assert result.manifest.missing_information
    assert not result.can_execute and not result.manifest.external_transfer_allowed


def test_budget_holds_entire_required_context_and_never_claims_provider_usage(db, sample):
    workspace, evidence, _ = sample
    writing_ready(db, workspace, evidence)
    req = request(workspace, evidence)
    normal = compile_task_context(db, "alice", req)
    held = compile_task_context(db, "alice", req.model_copy(update={"max_input_tokens": 1}))
    assert held.manifest.estimated_input_tokens == normal.manifest.estimated_input_tokens
    assert held.manifest.budget_status == "EXCEEDED" and held.payload is None
    assert held.manifest.references == normal.manifest.references
    assert "INPUT_BUDGET_EXCEEDED_NO_TRUNCATION" in held.manifest.missing_information
    assert held.manifest.model_ref is None and held.manifest.prompt_ref is None
    assert "NOT_PROVIDER_USAGE" in held.manifest.estimation_method


def test_no_writes_no_provider_no_embeddings_or_workflow_execution(db, sample, monkeypatch):
    workspace, evidence, _ = sample
    writing_ready(db, workspace, evidence)
    before = deepcopy(workspace.data)
    def forbidden(*args, **kwargs):
        pytest.fail("Read-only context attempted execution or external I/O")
    def select_only(conn, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith("SELECT"), statement
    for name in ("ai", "command", "ready", "freeze", "confirm_submission"):
        monkeypatch.setattr(Workflow, name, forbidden)
    monkeypatch.setattr("career.retrieval.configured_embedder", forbidden)
    event.listen(db.get_bind(), "before_cursor_execute", select_only)
    try:
        first = compile_task_context(db, "alice", request(workspace, evidence))
        assert compile_task_context(db, "alice", request(workspace, evidence)) == first
        application_plan(db, "alice", workspace.id)
        assert not db.new and not db.dirty and not db.deleted
        assert workspace.data == before
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", select_only)
    evidence.body = "uncommitted"
    with pytest.raises(ValueError, match="저장"):
        compile_task_context(db, "alice", request(workspace, evidence))


def test_rule_pack_and_transfer_flags_cannot_grant_unimplemented_authority(db, sample):
    workspace, evidence, _ = sample
    writing_ready(db, workspace, evidence)
    result = compile_task_context(db, "alice", request(workspace, evidence, approved_rule_pack_version="forged-approved"))
    assert result.status == "HOLD"
    assert result.manifest.rule_pack_status == "REQUESTED_VERSION_UNRESOLVED"
    assert result.manifest.consent_status == "NOT_EVALUATED_NO_EXTERNAL_TRANSFER"
    for changes in ({"external_transfer_consent": True}, {"user_id": "bob"}, {"namespace": "QUESTION_GUIDES"}):
        with pytest.raises(ValidationError):
            ContextRequest.model_validate({"task_type": "JOB_ASSESS", "application_id": workspace.id, **changes})


def test_skipped_required_step_is_blocked_and_cannot_satisfy_its_dependents(db, sample):
    workspace, _, _ = sample
    artifact(db, workspace, "OpportunityAssessment", status="SKIPPED", data={"eligibility": []})
    plan = application_plan(db, "alice", workspace.id)
    assert node(plan, "ELIGIBILITY").status == "BLOCKED"
    assert node(plan, "STRATEGY").status == "PLANNED"
    assert not plan.completion_proof and not plan.can_execute


@pytest.mark.parametrize("state", ["SUBMISSION_FROZEN", "SUBMITTED", "CLOSED"])
def test_context_for_frozen_or_closed_application_cannot_be_ready_for_writing(db, sample, state):
    workspace, evidence, _ = sample
    writing_ready(db, workspace, evidence)
    workspace.state = state
    db.commit()
    result = compile_task_context(db, "alice", request(workspace, evidence))
    assert result.status == "HOLD" and result.payload is None
    assert "APPLICATION_FROZEN_OR_CLOSED" in result.manifest.missing_information
    assert workspace.state == state


def test_context_never_follows_foreign_profile_fact_or_fact_source(db, sample):
    workspace, evidence, source = sample
    foreign, _ = register_source(db, "bob", "foreign-profile", "profile-private-marker", "RAW_RESULT")
    fact = add_fact(db, "bob", foreign.id, "profile", "education", {"text": "profile-private-marker"})
    db.commit()
    with pytest.raises(LookupError):
        compile_task_context(db, "alice", request(workspace, evidence, required_fact_ids=(fact.id,)))
    fact.user_id = "alice"
    db.commit()
    with pytest.raises(LookupError):
        compile_task_context(db, "alice", request(workspace, evidence, required_fact_ids=(fact.id,)))


def test_preferences_cannot_outlive_scope_fingerprint_or_source(db, sample):
    from career.entities import WritingRuleRecord
    from career.truth import owned

    workspace, evidence, _ = sample
    writing_ready(db, workspace, evidence)
    pref = direct_preference(db, "alice", "명시적으로 선택한 문체", confirmed=True)
    db.commit()
    req = request(workspace, evidence)
    first = compile_task_context(db, "alice", req)
    assert first.payload is not None and len(first.payload["preferences"]) == 1
    record = owned(db, WritingRuleRecord, "alice", pref["id"])
    record.data = {**record.data, "rule": "unapproved-change-marker"}
    db.commit()
    second = compile_task_context(db, "alice", req)
    assert second.payload is not None and not second.payload["preferences"]
    assert "unapproved-change-marker" not in second.model_dump_json()
    assert first.manifest.revision != second.manifest.revision


def test_current_question_scope_and_limits_change_context_revision(db, sample):
    workspace, evidence, _ = sample
    writing_ready(db, workspace, evidence)
    q = Workflow(db, "alice").add_question(workspace.id, "역량을 설명하세요", 600)
    artifact(db, workspace, "QuestionBrief", slot=q["id"], data={"evidence_ids": [evidence.id]})
    req = request(workspace, evidence, "COVER_WRITE", question_id=q["id"])
    first = compile_task_context(db, "alice", req)
    original = deepcopy(workspace.data)
    workspace.data = {**original, "questions": [{**item, "limit": 800} if item["id"] == q["id"] else item
                                               for item in original["questions"]]}
    db.commit()
    second = compile_task_context(db, "alice", req)
    assert second.payload is not None and second.payload["question"]["limit"] == 800
    assert first.manifest.revision != second.manifest.revision
    with pytest.raises(LookupError):
        compile_task_context(db, "alice", req.model_copy(update={"question_id": "other-application-question"}))
