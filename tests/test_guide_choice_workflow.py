# ruff: noqa: F811 -- shared fixtures
from copy import deepcopy

import pytest
from career.artifacts import latest
from career.guide_choices import (
    GuideChoiceRequest,
    QuestionConfirmation,
    confirm_question,
    contract_state,
    search_preview,
    select_guide,
)
from career.models import Artifact, Source
from career.providers import FakeLLMProvider
from career.question_contracts import LengthPolicy
from career.scoped_context import ContextRequest, compile_task_context
from career.workflow import Workflow
from career.writing_plans import digest, public_preview
from pydantic import ValidationError
from sqlalchemy import event, select
from test_question_guide_retrieval import policy, release, source
from test_workflow import doc, flow, verify_claim  # noqa: F401


@pytest.fixture
def choice_flow(flow, monkeypatch):
    from career.question_guide_import import normalize

    f, w, evidence = flow
    f.approve_strategy(w.id)
    text = "직무 전문역량과 실제 수행 근거를 설명하세요."
    q = f.add_question(w.id, text, 600)
    record = normalize(source(source_scope={"company": w.company, "role": w.role, "question_id": "Q1"}))
    reviews = [release(record)]
    rows = [record]
    monkeypatch.setenv("CAREER_GUIDE_SELECTION_ENABLED", "1")
    monkeypatch.setattr("career.guide_choices.catalog_snapshot", lambda: (tuple(rows), tuple(reviews), "CONFIGURED"))
    state = contract_state(f, w.id, q["id"])
    confirm_question(f, w.id, q["id"], QuestionConfirmation(expected_revision=state["state_revision"],
                     length=LengthPolicy.model_validate(policy()), confirmed=True), "confirm-1")
    f.db.commit()
    return f, w, evidence, q, rows, reviews


def choose(f, w, q, candidate=True, **changes):
    state = search_preview(f, w.id, q["id"])
    match = state["retrieval"]["candidates"][0] if candidate else None
    return GuideChoiceRequest.model_validate({"expected_revision": state["selection_revision"],
        "request_key": state["retrieval"]["request_key"], "guide_id": match["guide_id"] if match else None,
        "guide_version": match["guide_version"] if match else None,
        "guide_snapshot_hash": match["guide_snapshot_hash"] if match else None, **changes})


def manual_brief(evidence, qid):
    return {"question_id": qid, "question_type": "JOB_COMPETENCY", "evaluation_intent": "판단 검증",
            "primary_message": "평가를 검증했습니다.", "evidence_ids": [evidence.id]}


def test_chosen_snapshot_is_identical_on_screen_designer_and_writer_with_existing_claim_gate(choice_flow):
    f, w, evidence, q, _, _ = choice_flow
    picked = select_guide(f, w.id, q["id"], choose(f, w, q, allocation_budgets=[80, 120, 260, 140]), "choice-1")
    recorded = {}
    class Capture(FakeLLMProvider):
        def structured(self, stage, values, schema):
            recorded[stage] = deepcopy(values)
            return super().structured(stage, values, schema)
    f.provider = Capture({"question_brief": manual_brief(evidence, q["id"]), "writer": doc(evidence)})
    brief = f.question_brief(w.id, q["id"])
    with pytest.raises(ValueError):
        f.approve_question(w.id, q["id"])
    verify_claim(f, w, q["id"])
    f.approve_question(w.id, q["id"])
    f.draft(w.id, q["id"])
    screen = public_preview(f, w.id, q["id"])
    writer = recorded["writer"]["writing_plan"]
    assert recorded["question_brief"]["writing_plan"] == writer
    assert writer["guide"] == screen["guide"]
    assert writer["guide_snapshot_sha256"] == screen["guide_snapshot_sha256"] == digest(screen["guide"])
    assert [p["approximate_characters"] for p in writer["guide"]["allocation"]] == [80, 120, 260, 140]
    plan = latest(f.db, f.user, w.id, "WritingPlan", q["id"])
    assert plan is not None
    assert picked.id in plan.depends_on and plan.id in brief.depends_on
    assert writer["guide"]["reference_example"]["paragraphs"] == []
    assert picked.data["decision"] == "STRUCTURE_CHOSEN_NOT_CLAIM_APPROVAL"


def test_preview_is_select_only_and_calls_no_provider_or_mutation(choice_flow, monkeypatch):
    f, w, _, q, _, _ = choice_flow
    def forbidden(*args, **kwargs):
        pytest.fail("GET preview attempted provider or workflow execution")
    def select_only(conn, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith("SELECT"), statement
    monkeypatch.setattr(Workflow, "ai", forbidden)
    event.listen(f.db.get_bind(), "before_cursor_execute", select_only)
    try:
        first = search_preview(f, w.id, q["id"])
        assert search_preview(f, w.id, q["id"]) == first
        assert not f.db.new and not f.db.dirty and not f.db.deleted
    finally:
        event.remove(f.db.get_bind(), "before_cursor_execute", select_only)


@pytest.mark.parametrize("change", ["evidence", "question", "review", "guide"])
def test_stale_choice_request_has_no_partial_source_plan_or_decision_writes(choice_flow, change):
    from career.question_guide_import import normalize
    f, w, evidence, q, rows, reviews = choice_flow
    request = choose(f, w, q)
    if change == "evidence":
        evidence.body += " 실제 기록 정정"
    elif change == "question":
        w.data = {**w.data, "questions": [{**q, "limit": 800}]}
    elif change == "review":
        reviews[:] = [reviews[0].model_copy(update={"source_rights": "RESTRICTED"})]
    else:
        rows[:] = [normalize(source(version=2, source_scope={"company": w.company, "role": w.role, "question_id": "Q1"}))]
    f.db.commit()
    before = (list(f.db.scalars(select(Artifact.id))), list(f.db.scalars(select(Source.id))))
    with pytest.raises(ValueError):
        select_guide(f, w.id, q["id"], request, "stale-request")
    assert before == (list(f.db.scalars(select(Artifact.id))), list(f.db.scalars(select(Source.id))))


def test_current_demands_count_and_excluded_topic_override_curated_guide(choice_flow):
    f, w, _, q, _, _ = choice_flow
    state = contract_state(f, w.id, q["id"])
    confirm_question(f, w.id, q["id"], QuestionConfirmation(expected_revision=state["state_revision"],
        length=LengthPolicy.model_validate(policy()), required_demands=("전문역량", "개인 기여 비율"), excluded_topics=("기술적 행동",), confirmed=True), "new-demands")
    preview = search_preview(f, w.id, q["id"])
    assert not preview["retrieval"]["candidates"]
    assert preview["question_contract"]["required_demands"] == ["전문역량", "개인 기여 비율"]
    assert preview["retrieval"]["rejected"][0]["missing_demands"] == ["개인 기여 비율"]
    select_guide(f, w.id, q["id"], choose(f, w, q, False), "fallback-1")
    guide = public_preview(f, w.id, q["id"])["guide"]
    assert guide["question_contract"]["excluded_topics"] == ["기술적 행동"]
    f.db.commit()
    pack = compile_task_context(f.db, f.user, ContextRequest(task_type="COVER_WRITE", application_id=w.id,
                                question_id=q["id"], required_evidence_ids=()))
    assert any(r.kind == "QUESTION_CONTRACT" for r in pack.manifest.references)


def test_choice_change_stales_only_related_chain_and_preserves_frozen_history(choice_flow):
    f, w, evidence, q, _, _ = choice_flow
    select_guide(f, w.id, q["id"], choose(f, w, q), "first-choice")
    f.question_brief(w.id, q["id"], manual_brief(evidence, q["id"]))
    verify_claim(f, w, q["id"])
    f.approve_question(w.id, q["id"])
    draft = f.draft(w.id, q["id"], doc(evidence))
    review = f.review(w.id, q["id"], manual_verified=True)
    unrelated = Artifact(user_id=f.user, workspace_id=w.id, kind="WritingPlan", slot="another-q", version=1,
                         status="LOCKED", data={"marker": "preserve-other-question"})
    bundle = Artifact(user_id=f.user, workspace_id=w.id, kind="SubmissionBundle", version=1, status="LOCKED",
                      data={"documents": [deepcopy(draft.data)]}, depends_on=[draft.id])
    f.db.add_all([unrelated, bundle])
    f.db.flush()
    before = deepcopy(bundle.data)
    select_guide(f, w.id, q["id"], choose(f, w, q, False), "changed-choice")
    assert draft.status == review.status == "STALE"
    assert unrelated.status == "LOCKED"
    assert bundle.data == before and bundle.status == "LOCKED" and evidence.status == "VERIFIED"
    with pytest.raises(ValueError):
        f.draft(w.id, q["id"], doc(evidence))


@pytest.mark.parametrize("stage", ["draft", "final_lock", "ready", "freeze"])
def test_revoked_catalog_choice_cannot_be_reused_at_any_final_gate(choice_flow, stage):
    f, w, evidence, q, _, reviews = choice_flow
    select_guide(f, w.id, q["id"], choose(f, w, q), "chosen")
    f.question_brief(w.id, q["id"], manual_brief(evidence, q["id"]))
    verify_claim(f, w, q["id"])
    f.approve_question(w.id, q["id"])
    f.draft(w.id, q["id"], doc(evidence))
    f.review(w.id, q["id"], manual_verified=True)
    f.final_lock(w.id, q["id"])
    reviews[:] = [reviews[0].model_copy(update={"source_rights": "RESTRICTED"})]
    preview = public_preview(f, w.id, q["id"])
    assert not preview["guide_choice"]["current"] and not preview["can_design"]
    with pytest.raises(ValueError):
        if stage in {"draft", "final_lock"}:
            getattr(f, stage)(w.id, q["id"])
        else:
            getattr(f, stage)(w.id)


def test_idempotent_replay_returns_original_decision_and_rejects_changed_payload(choice_flow):
    f, w, _, q, _, _ = choice_flow
    request = choose(f, w, q)
    first = select_guide(f, w.id, q["id"], request, "stable-key")
    ids = list(f.db.scalars(select(Artifact.id)))
    assert select_guide(f, w.id, q["id"], request, "stable-key").id == first.id
    assert ids == list(f.db.scalars(select(Artifact.id)))
    with pytest.raises(ValueError, match="같은 요청"):
        select_guide(f, w.id, q["id"], request.model_copy(update={"allocation_budgets": (50, 100, 250, 150)}), "stable-key")


@pytest.mark.parametrize("changes", [{"guide": {"fake": "body"}}, {"approved": True}, {"user_id": "bob"}])
def test_untrusted_guide_body_and_approval_fields_are_not_decisions(changes):
    with pytest.raises(ValidationError):
        GuideChoiceRequest.model_validate({"expected_revision": "a" * 64, "request_key": "b" * 64, **changes})


@pytest.mark.parametrize("policy_change", [{"unit": "BYTES"}, {"spaces": "EXCLUDED"}, {"title": "EXCLUDED"}])
def test_unsupported_form_counter_is_saved_but_cannot_silently_use_character_qa(choice_flow, policy_change):
    f, w, evidence, q, _, _ = choice_flow
    state = contract_state(f, w.id, q["id"])
    confirm_question(f, w.id, q["id"], QuestionConfirmation(expected_revision=state["state_revision"],
                      length=LengthPolicy.model_validate(policy(**policy_change)), confirmed=True), "counter-policy")
    select_guide(f, w.id, q["id"], choose(f, w, q, False), "counter-fallback")
    state = public_preview(f, w.id, q["id"])
    assert not state["can_design"] and state["writing_hold_notice"]
    with pytest.raises(ValueError, match="계수 방식"):
        f.question_brief(w.id, q["id"], manual_brief(evidence, q["id"]))


def test_guide_search_and_choice_are_owner_and_question_scoped(choice_flow):
    f, w, _, q, _, _ = choice_flow
    with pytest.raises(LookupError):
        search_preview(Workflow(f.db, "bob"), w.id, q["id"])
    with pytest.raises(LookupError):
        search_preview(f, w.id, "different-application-question")


def test_current_minimum_applies_to_budget_and_generated_document(choice_flow):
    f, w, evidence, q, _, _ = choice_flow
    state = contract_state(f, w.id, q["id"])
    confirm_question(f, w.id, q["id"], QuestionConfirmation(expected_revision=state["state_revision"],
        length=LengthPolicy.model_validate(policy(minimum=500)), confirmed=True), "minimum-1")
    with pytest.raises(ValueError, match="분량"):
        select_guide(f, w.id, q["id"], choose(f, w, q, allocation_budgets=[10, 10, 10, 10]), "invalid-budgets")
    select_guide(f, w.id, q["id"], choose(f, w, q), "valid-minimum")
    f.question_brief(w.id, q["id"], manual_brief(evidence, q["id"]))
    verify_claim(f, w, q["id"])
    f.approve_question(w.id, q["id"])
    with pytest.raises(ValueError, match="최소·최대"):
        f.draft(w.id, q["id"], doc(evidence))


def test_unrelated_new_curator_guide_does_not_invalidate_current_selected_snapshot(choice_flow):
    from career.question_guide_import import normalize
    f, w, _, q, rows, reviews = choice_flow
    select_guide(f, w.id, q["id"], choose(f, w, q), "selected-stable")
    before = public_preview(f, w.id, q["id"])
    other = normalize(source(guide_id="unrelated", question="가치관을 보여준 경험을 설명하세요.", required_demands=[]))
    rows.append(other)
    reviews.append(release(other))
    after = public_preview(f, w.id, q["id"])
    assert after["guide_choice"]["current"]
    assert after["guide_snapshot_sha256"] == before["guide_snapshot_sha256"]
    assert after["state_revision"] == before["state_revision"]
