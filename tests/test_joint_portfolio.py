# ruff: noqa: F811 -- reusable workflow fixture
from copy import deepcopy

import pytest
from career.artifacts import latest, save
from career.entities import MetricRecord
from career.experience_options import ExperienceChoiceRequest, options
from career.experience_options import choose as choose_experience
from career.joint_portfolio import DecisionRequest, ProposalRequest, decide, inputs, preview, propose
from career.models import Artifact, Evidence, Source
from career.portfolio import approve, plan
from career.providers import FakeLLMProvider
from career.truth import add_evidence, register_source
from career.workflow import Workflow
from career.writing_plans import public_preview
from sqlalchemy import event, select
from test_workflow import doc, flow, verify_claim  # noqa: F401


@pytest.fixture
def joint(flow):
    f, w, e = flow
    f.approve_strategy(w.id)
    qs = [f.add_question(w.id, text, 1000) for text in ("직무 역량", "협업에서 판단한 기준", "어려운 과제 해결")]
    f.db.commit()
    return f, w, e, qs


def worksheet(f, w):
    state = preview(f, w.id)
    return propose(f, w.id, ProposalRequest(expected_revision=state["input_revision"]), "proposal-0001")


def decision_request(f, w, e, *, disposition="DIRECT", **changes):
    state = preview(f, w.id)
    items = [{"question_id": q["id"], "identity_role": f"판단 역할 {index}",
              "primary_message": [e.body, "정확도를 확인했습니다.", "실험 결과를 검토했습니다."][index % 3], "evidence_ids": [e.id],
              "evidence_role": f"수행 범위 {index}", "metric_ids": [], "climax": f"원문에서 검토할 핵심 장면 {index}"}
             for index, q in enumerate(state["questions"])]
    body = {"expected_revision": state["decision_revision"], "proposal_id": state["proposal"]["id"],
            "proposal_version": state["proposal"]["version"], "disposition": disposition,
            "persona_text": "평가 실험의 판단 근거를 설명하는 연구원", "items": items, **changes}
    if disposition in {"REJECT", "HOLD"}:
        body.update(persona_text="", items=[], reason="현재 근거를 더 확인하겠습니다.")
    return DecisionRequest.model_validate(body)


def accept(joint):
    f, w, e, _ = joint
    worksheet(f, w)
    decision = decide(f, w.id, decision_request(f, w, e), "decision-001")
    return decision


def brief_data(decision, q):
    item = next(i for i in decision.data["items"] if i["question_id"] == q["id"])
    return {"question_id": q["id"], "question_type": "JOB_COMPETENCY", "evaluation_intent": "판단 근거",
            "primary_message": item["primary_message"], "evidence_ids": item["evidence_ids"]}


def test_get_is_read_only_and_proposal_never_selects_persona_or_locks_strategy(joint, monkeypatch):
    f, w, _, _ = joint
    monkeypatch.setattr(Workflow, "ai", lambda *a, **k: pytest.fail("GET/offline called AI"))
    def select_only(conn, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith("SELECT")
    event.listen(f.db.get_bind(), "before_cursor_execute", select_only)
    try:
        before = preview(f, w.id)
        assert before == preview(f, w.id)
        assert not f.db.dirty and not f.db.new
    finally:
        event.remove(f.db.get_bind(), "before_cursor_execute", select_only)
    proposal = worksheet(f, w)
    assert not proposal.data["selected"] and proposal.status == "ACTIVE"
    assert latest(f.db, f.user, w.id, "PersonaDecision", required=False) is None
    assert f.artifact(w.id, "ApplicationBrief").status == "LOCKED"


def test_three_questions_need_complete_allocation_persona_strategy_and_portfolio_approvals(joint):
    f, w, e, qs = joint
    worksheet(f, w)
    request = decision_request(f, w, e)
    with pytest.raises(ValueError, match="모든 문항"):
        decide(f, w.id, request.model_copy(update={"items": request.items[:-1]}), "incomplete-1")
    assert latest(f.db, f.user, w.id, "PersonaDecision", required=False) is None
    decision = decide(f, w.id, request, "complete-1")
    assert f.artifact(w.id, "PersonaDecision").status == "ACTIVE"
    assert f.artifact(w.id, "QuestionPortfolio").status == "ACTIVE"
    with pytest.raises(ValueError, match="전략"):
        approve(f, w.id)
    with pytest.raises(ValueError):
        f.question_brief(w.id, qs[0]["id"], brief_data(decision, qs[0]))
    f.approve_strategy(w.id)
    assert f.artifact(w.id, "PersonaDecision").status == "LOCKED"
    with pytest.raises(ValueError, match="승인"):
        f.question_brief(w.id, qs[0]["id"], brief_data(decision, qs[0]))
    approve(f, w.id)
    f.question_brief(w.id, qs[0]["id"], brief_data(decision, qs[0]))
    with pytest.raises(ValueError):
        f.approve_question(w.id, qs[0]["id"])
    verify_claim(f, w, qs[0]["id"])
    f.approve_question(w.id, qs[0]["id"])
    f.draft(w.id, qs[0]["id"], doc(e))
    assert public_preview(f, w.id, qs[0]["id"])["material_selection"]["material"]["evidence_ids"] == [e.id]
    with pytest.raises(ValueError):
        f.ready(w.id)  # Other questions are not written or locked.


@pytest.mark.parametrize("field", ["identity_role", "primary_message", "evidence_role", "climax"])
def test_same_project_allowed_only_when_message_role_and_climax_are_distinct(joint, field):
    f, w, e, _ = joint
    worksheet(f, w)
    request = decision_request(f, w, e)
    items = list(request.items)
    items[1] = items[1].model_copy(update={field: "  " + getattr(items[0], field) + "  "})
    with pytest.raises(ValueError, match="중복|구별"):
        decide(f, w.id, request.model_copy(update={"items": tuple(items)}), "duplicate-1")
    decide(f, w.id, request, "distinct-1")


@pytest.mark.parametrize("disposition", ["HOLD", "REJECT"])
def test_reject_and_hold_preserve_history_and_block_legacy_bypasses(joint, disposition):
    f, w, e, qs = joint
    chosen = accept(joint)
    f.approve_strategy(w.id)
    approve(f, w.id)
    brief = f.question_brief(w.id, qs[0]["id"], brief_data(chosen, qs[0]))
    verify_claim(f, w, qs[0]["id"])
    f.approve_question(w.id, qs[0]["id"])
    draft = f.draft(w.id, qs[0]["id"], doc(e))
    frozen, _ = save(f.db, f.user, w.id, "SubmissionBundle", {"text": "immutable history", "frozen_at": "2026-10-23T00:00:00+00:00"}, deps=[draft.id])
    original = deepcopy(frozen.data)
    result = decide(f, w.id, decision_request(f, w, e, disposition=disposition), "reject-or-hold")
    assert result.data["selected_evidence_ids"] == [] and result.status == "ACTIVE"
    assert brief.status == draft.status == "STALE"
    assert frozen.data == original and frozen.status == "ACTIVE"
    for action in (lambda: approve(f, w.id), lambda: f.final_lock(w.id, qs[0]["id"]),
                   lambda: f.ready(w.id), lambda: f.freeze(w.id), lambda: plan(f, w.id, {"items": []})):
        with pytest.raises(ValueError):
            action()


def test_missing_ownership_is_hold_and_cannot_be_upgraded_by_preference(joint):
    f, w, e, _ = joint
    e.data = {**e.data, "ownership": {"implementation": "UNKNOWN"}}
    f.db.commit()
    state = preview(f, w.id)
    assert state["candidates"][0]["classification"] == "DIRECT"  # Existing mapping is never rewritten.
    assert state["candidates"][0]["eligibility"] == "HOLD"
    worksheet(f, w)
    with pytest.raises(ValueError, match="HOLD"):
        decide(f, w.id, decision_request(f, w, e), "unknown-owner")
    assert e.data["ownership"]["implementation"] == "UNKNOWN"


def test_private_evidence_only_and_other_application_persona_never_leaks(joint):
    f, w, e, _ = joint
    accept(joint)
    other = f.create("다른회사", "연구원", "검증")
    assert latest(f.db, f.user, other.id, "PersonaDecision", required=False) is None
    assert latest(f.db, "other-user", w.id, "PersonaDecision", required=False) is None
    with pytest.raises(LookupError):
        preview(Workflow(f.db, "other-user"), w.id)
    state = preview(f, w.id)
    source, _ = register_source(f.db, "other-user", "other", "private-marker", "RAW_RESULT")
    alien = add_evidence(f.db, "other-user", source.id, "private-marker", "private-marker", {}, "VERIFIED")
    request = decision_request(f, w, e)
    items = (request.items[0].model_copy(update={"evidence_ids": (alien.id,)}), *request.items[1:])
    with pytest.raises(ValueError):
        decide(f, w.id, request.model_copy(update={"items": items}), "alien-evidence")
    assert "private-marker" not in str(state)


def test_explicit_experience_selection_cannot_be_silently_replaced(joint):
    f, w, e, qs = joint
    opts = options(f, w.id, qs[0]["id"])
    choose_experience(f, w.id, ExperienceChoiceRequest(slot=qs[0]["id"], evidence_id=e.id,
        base_artifact_id=opts["base_artifact_id"], base_artifact_version=opts["base_artifact_version"], options_revision=opts["options_revision"]))
    f.db.commit()
    worksheet(f, w)
    req = decision_request(f, w, e)
    items = (req.items[0].model_copy(update={"evidence_ids": ()}), *req.items[1:])
    with pytest.raises(ValueError, match="조용히 대체"):
        decide(f, w.id, req.model_copy(update={"items": items}), "replace-choice")


@pytest.mark.parametrize("change", ["question", "evidence", "strategy"])
def test_stale_proposal_decision_has_no_partial_product_writes(joint, change):
    f, w, e, _ = joint
    worksheet(f, w)
    req = decision_request(f, w, e)
    if change == "question":
        f.add_question(w.id, "새 문항", 600)
    elif change == "evidence":
        e.body += " 정정"
    else:
        strategy = f.artifact(w.id, "ApplicationBrief")
        strategy.data = {**strategy.data, "positioning": "정정된 표현"}
    f.db.commit()
    before = list(f.db.scalars(select(Artifact.id)))
    with pytest.raises(ValueError):
        decide(f, w.id, req, "old-decision")
    assert list(f.db.scalars(select(Artifact.id))) == before


def test_ai_proposal_is_context_scoped_versioned_and_user_can_modify_combine(joint):
    f, w, e, _ = joint
    state = preview(f, w.id)
    items = [{"question_id": q["id"], "identity_role": f"역할{i}", "primary_message": f"메시지{i}",
              "evidence_ids": [e.id], "evidence_role": f"수행{i}", "climax": f"장면{i}"} for i, q in enumerate(state["questions"])]
    values = {"personas": [{"text": text, "evidence_ids": [e.id], "limitation": "측정·수행 범위 안의 제안"}
                           for text in ("실험을 설계하는 연구원", "근거를 검증하는 연구원")], "items": items}
    captured = {}
    class Capture(FakeLLMProvider):
        def structured(self, stage, context, schema):
            captured.update(context)
            return super().structured(stage, context, schema)
    f.provider = Capture({"joint_portfolio": values})
    proposal = propose(f, w.id, ProposalRequest(expected_revision=state["input_revision"], use_ai=True, external_transfer_confirmed=True), "ai-proposal-1")
    assert captured["context_manifest"]["owner_id"] == f.user
    assert captured["context_pack"]["experiences"][0]["id"] == e.id
    assert all("reference_example" not in g["guide"] for g in captured["guides"].values())
    current = preview(f, w.id)
    original_choice = decide(f, w.id, DecisionRequest(expected_revision=current["decision_revision"],
        proposal_id=proposal.id, proposal_version=proposal.version, disposition="ACCEPT",
        persona_candidate_ids=(proposal.data["personas"][0]["candidate_id"],)), "accept-original")
    assert original_choice.data["is_selection"] and f.artifact(w.id, "PersonaDecision").status == "ACTIVE"
    req = decision_request(f, w, e, disposition="COMBINE", persona_candidate_ids=[p["candidate_id"] for p in proposal.data["personas"]])
    result = decide(f, w.id, req, "combine-persona")
    assert result.data["disposition"] == "COMBINE" and result.version == 2
    assert f.artifact(w.id, "PersonaDecision").status == "ACTIVE"
    request = decision_request(f, w, e, disposition="MODIFY", persona_text="직접 고친 표현")
    request = request.model_copy(update={"items": (request.items[0].model_copy(update={"primary_message": "수정한 메시지", "climax": "새로 정한 판단 장면"}), *request.items[1:])})
    modified = decide(f, w.id, request, "modify-persona")
    assert modified.version == 3 and modified.data["proposal_version"] == proposal.version
    assert f.artifact(w.id, "PersonaDecision").data["text"] == "직접 고친 표현"
    assert not modified.data["claim_approval_granted"]
    hint = public_preview(f, w.id, state["questions"][0]["id"])["material_selection"]
    assert hint["decision_id"] == modified.id and hint["material"]["primary_message"] == "수정한 메시지"
    assert hint["material"]["climax"] == "새로 정한 판단 장면" and not hint["approvals_ready"]


def test_idempotency_and_budget_never_duplicate_or_call_provider_without_room(joint, monkeypatch):
    f, w, e, _ = joint
    worksheet(f, w)
    req = decision_request(f, w, e)
    first = decide(f, w.id, req, "same-decision")
    assert decide(f, w.id, req, "same-decision").id == first.id
    with pytest.raises(ValueError, match="같은 요청"):
        decide(f, w.id, req.model_copy(update={"reason": "changed"}), "same-decision")
    monkeypatch.setattr(Workflow, "ai", lambda *a, **k: pytest.fail("over budget called provider"))
    with pytest.raises(ValueError):
        propose(f, w.id, ProposalRequest(expected_revision=inputs(f, w.id)["input_revision"], use_ai=True, external_transfer_confirmed=True, max_input_tokens=1), "too-small-budget")


def test_metric_repetition_and_foreign_metric_rejected_without_truth_upgrade(joint):
    f, w, e, _ = joint
    metric = MetricRecord(user_id=f.user, evidence_id=e.id, source_id=e.source_id, status="VERIFIED",
                          data={"name": "정확도", "value": "80", "unit": "%", "measurement_context": "EXPERIMENT"})
    f.db.add(metric)
    f.db.commit()
    worksheet(f, w)
    request = decision_request(f, w, e)
    items = list(request.items)
    items[0] = items[0].model_copy(update={"metric_ids": (metric.id,)})
    items[1] = items[1].model_copy(update={"metric_ids": (metric.id,)})
    with pytest.raises(ValueError, match="같은 수치"):
        decide(f, w.id, request.model_copy(update={"items": tuple(items)}), "repeated-metric")
    items[1] = items[1].model_copy(update={"metric_ids": ("foreign-or-invented",)})
    with pytest.raises(ValueError, match="연결된 현재 수치"):
        decide(f, w.id, request.model_copy(update={"items": tuple(items)}), "foreign-metric")
    assert metric.status == "VERIFIED" and metric.data["measurement_context"] == "EXPERIMENT"


def test_reference_example_cannot_be_selected_as_applicant_fact(joint):
    f, w, e, _ = joint
    source, _ = register_source(f.db, f.user, "guide-example", "외부 예시 프로젝트", "REFERENCE")
    with pytest.raises(ValueError, match="경험 사실"):
        add_evidence(f.db, f.user, source.id, "외부 예시", "실제 지원자의 수행이 아님", {}, "VERIFIED")
    example = Evidence(user_id=f.user, source_id=source.id, title="외부 예시", body="실제 지원자의 수행이 아님",
                       kind="EVIDENCE", status="VERIFIED", data={"ownership": {"implementation": "USER"}})
    f.db.add(example)
    f.db.flush()
    pack = f.artifact(w.id, "EvidencePack")
    # Simulate a corrupted prior mapping: selection still validates the real Source authority.
    pack.data = {**pack.data, "items": [*pack.data["items"], {**pack.data["items"][0], "evidence_id": example.id}]}
    f.db.commit()
    assert next(c for c in preview(f, w.id)["candidates"] if c["evidence_id"] == example.id)["eligibility"] == "HOLD"
    worksheet(f, w)
    request = decision_request(f, w, e)
    items = (request.items[0].model_copy(update={"evidence_ids": (example.id,)}), *request.items[1:])
    with pytest.raises(ValueError, match="HOLD"):
        decide(f, w.id, request.model_copy(update={"items": items}), "example-fact")


def test_choice_does_not_invalidate_another_application_and_feature_off_does_not_bypass(joint, monkeypatch):
    f, w, e, qs = joint
    other = f.create("별도회사", "연구원", "평가")
    independent = Artifact(user_id=f.user, workspace_id=other.id, kind="Draft", slot="independent",
                           status="LOCKED", data={"text": "independent history"})
    f.db.add(independent)
    f.db.commit()
    accepted = accept(joint)
    assert independent.status == "LOCKED" and independent.data["text"] == "independent history"
    monkeypatch.setenv("CAREER_JOINT_PORTFOLIO_ENABLED", "0")
    with pytest.raises(ValueError, match="전략"):
        f.question_brief(w.id, qs[0]["id"], brief_data(accepted, qs[0]))


@pytest.mark.parametrize("change", ["guide", "ownership", "source"])
def test_changed_sources_and_guide_hold_every_final_gate(joint, change, monkeypatch):
    f, w, e, qs = joint
    accepted = accept(joint)
    f.approve_strategy(w.id)
    approve(f, w.id)
    f.question_brief(w.id, qs[0]["id"], brief_data(accepted, qs[0]))
    verify_claim(f, w, qs[0]["id"])
    f.approve_question(w.id, qs[0]["id"])
    f.draft(w.id, qs[0]["id"], doc(e))
    if change == "guide":
        from career.joint_portfolio import resolve as original
        def revised(*args):
            guide, choice, deps = original(*args)
            return {**guide, "question_intent": "새로 검토한 의도"}, choice, deps
        monkeypatch.setattr("career.joint_portfolio.resolve", revised)
    elif change == "ownership":
        e.data = {**e.data, "ownership": {"implementation": "UNKNOWN"}}
    else:
        owned_source = f.db.get(Source, e.source_id)
        assert owned_source is not None
        owned_source.status = "DO_NOT_USE"
    f.db.commit()
    for action in (lambda: f.approve_question(w.id, qs[0]["id"]), lambda: f.draft(w.id, qs[0]["id"], doc(e)),
                   lambda: f.final_lock(w.id, qs[0]["id"]), lambda: f.ready(w.id), lambda: f.freeze(w.id)):
        with pytest.raises(ValueError):
            action()


def test_actual_selected_material_and_persona_are_same_in_plan_brief_and_writer(joint):
    f, w, e, qs = joint
    accepted = accept(joint)
    f.approve_strategy(w.id)
    approve(f, w.id)
    seen = {}
    class Capture(FakeLLMProvider):
        def structured(self, stage, context, schema):
            seen[stage] = deepcopy(context)
            return super().structured(stage, context, schema)
    f.provider = Capture({"question_brief": brief_data(accepted, qs[0]), "writer": doc(e)})
    f.question_brief(w.id, qs[0]["id"])
    verify_claim(f, w, qs[0]["id"])
    f.approve_question(w.id, qs[0]["id"])
    f.draft(w.id, qs[0]["id"])
    on_screen = public_preview(f, w.id, qs[0]["id"])["material_selection"]
    assert seen["question_brief"]["writing_plan"]["material_selection"] == on_screen
    assert seen["writer"]["writing_plan"]["material_selection"] == on_screen
    assert seen["question_brief"]["selected_material"] == on_screen["material"]
    assert on_screen["decision_id"] == accepted.id and on_screen["fact_authority"] is False
