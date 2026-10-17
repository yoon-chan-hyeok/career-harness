# ruff: noqa: F811 -- shared workflow fixture
from copy import deepcopy

import pytest
from career.artifacts import latest
from career.models import Artifact
from career.providers import FakeLLMProvider
from career.writing_plans import PlanRequest, context, digest, guide_for, persist, public_preview
from sqlalchemy import select
from test_workflow import doc, flow, question, verify_claim  # noqa: F401


def setup(flow):
    f, w, e = flow
    f.approve_strategy(w.id)
    q = f.add_question(w.id, "직무 역량을 설명하세요.", 600)
    return f, w, e, q


def edit(f, w, q, **changes):
    state = public_preview(f, w.id, q["id"])
    return persist(f, w.id, q["id"], PlanRequest(expected_revision=state["state_revision"], **changes))


def test_archived_guide_exact_company_role_question_and_length_only():
    text = "해당 분야에서 타인과 차별화될 수 있는 전문역량은 무엇인지 구체적으로 설명해 주시길 바랍니다. (600자)"
    q = {"id": "q", "text": text, "limit": 600}
    guide = guide_for("포스코DX", "SW 개발", q)
    assert guide["origin"] == "ARCHIVED_REFERENCE"
    assert guide["reference_example"]["total_characters"] == 592
    assert [i["approximate_characters"] for i in guide["allocation"]] == [70, 120, 280, 130]
    for company, role, other in [("다른 회사", "SW 개발", q), ("포스코DX", "AI 개발", q),
                                  ("포스코DX", "SW 개발", {**q, "limit": 800}),
                                  ("포스코DX", "SW 개발", {**q, "text": "전문역량과 실패를 설명하세요."})]:
        result = guide_for(company, role, other)
        assert result["origin"] == "SUGGESTED_STRUCTURE"
        assert result["source"] is None
        assert "포스코DX" not in str(result["reference_example"])


@pytest.mark.parametrize("text,kind", [
    ("지원동기는 무엇인가요?", "MOTIVATION"), ("동료와 갈등을 해결한 경험", "COLLABORATION"),
    ("가장 큰 도전과 실패", "CHALLENGE"), ("나의 강점과 약점", "STRENGTH_WEAKNESS"),
    ("중요한 가치관은?", "VALUES"), ("직무 역량은?", "JOB_COMPETENCY"), ("자유롭게 소개", "OTHER"),
])
def test_each_question_has_labelled_advisory_plan_not_a_fake_published_guide(text, kind):
    result = guide_for("회사", "직무", {"text": text, "limit": 713})
    assert result["question_type"] == kind
    assert sum(i["approximate_characters"] for i in result["allocation"]) == 713
    assert result["fixed_body_paragraph_count"] is False
    assert result["reference_example"]["use_as_applicant_fact"] is False


def test_preview_is_read_only_and_missing_strategy_is_visible(flow):
    f, w, e = flow
    q = f.add_question(w.id, "직무 역량", 600)
    before = list(f.db.scalars(select(Artifact.id)))
    state = public_preview(f, w.id, q["id"])
    assert state["can_design"] is False
    assert state["missing_information"]
    assert list(f.db.scalars(select(Artifact.id))) == before
    assert not any(key.startswith("_") for key in state)


def test_same_preparation_is_idempotent_and_saved_notes_not_facts(flow):
    f, w, e, q = setup(flow)
    first = edit(f, w, q, working_notes="강조하고 싶은 장면")
    second = edit(f, w, q, working_notes="강조하고 싶은 장면")
    assert second.id == first.id
    assert public_preview(f, w.id, q["id"])["plan_current"]
    assert context(first)["notes_are_verified_facts"] is False
    assert context(first)["guide"] == public_preview(f, w.id, q["id"])["guide"]
    assert digest(context(first)["guide"]) == first.data["guide_snapshot_sha256"]


def test_stale_edit_rejected_after_evidence_changed(flow):
    f, w, e, q = setup(flow)
    state = public_preview(f, w.id, q["id"])
    e.body += " 원문 보완."
    with pytest.raises(ValueError, match="바뀌었"):
        persist(f, w.id, q["id"], PlanRequest(expected_revision=state["state_revision"]))
    assert latest(f.db, f.user, w.id, "WritingPlan", q["id"], required=False) is None


def test_guide_and_actual_question_reach_both_question_designer_and_writer(flow):
    f, w, e, q = setup(flow)
    plan = edit(f, w, q, emphasis_state="active", emphasis="판단을 먼저",
                working_notes="검증 전 메모")
    recorded = {}
    class Capture(FakeLLMProvider):
        def structured(self, stage, values, schema):
            recorded[stage] = deepcopy(values)
            return super().structured(stage, values, schema)
    f.provider = Capture({
        "question_brief": {"question_id": q["id"], "question_type": "JOB_COMPETENCY",
                           "evaluation_intent": "판단 검증", "primary_message": "평가를 검증했습니다.",
                           "evidence_ids": [e.id]},
        "writer": doc(e),
    })
    brief = f.question_brief(w.id, q["id"])
    verify_claim(f, w, q["id"])
    f.approve_question(w.id, q["id"])
    draft = f.draft(w.id, q["id"])
    assert brief.data["writing_plan_id"] == plan.id
    assert plan.id in brief.depends_on
    assert recorded["question_brief"]["writing_plan"] == recorded["writer"]["writing_plan"]
    assert recorded["writer"]["actual_target_question"]["text"] == q["text"]
    assert recorded["writer"]["writing_plan"]["emphasis"] == "판단을 먼저"
    assert recorded["writer"]["evidence"][0]["id"] == e.id
    assert recorded["writer"]["writing_plan"]["reference_examples_are_applicant_facts"] is False
    assert public_preview(f, w.id, q["id"])["phase"] == "REVIEW"
    assert draft.status == "ACTIVE"


def test_changing_plan_invalidates_claim_proof_draft_and_review(flow):
    f, w, e, q = setup(flow)
    brief = f.question_brief(w.id, q["id"], {
        "question_id": q["id"], "question_type": "JOB_COMPETENCY", "evaluation_intent": "검증",
        "primary_message": "평가를 검증했습니다.", "evidence_ids": [e.id]})
    proof = verify_claim(f, w, q["id"])
    f.approve_question(w.id, q["id"])
    draft = f.draft(w.id, q["id"], doc(e))
    review = f.review(w.id, q["id"], manual_verified=True)
    changed = edit(f, w, q, working_notes="다른 장면을 검토")
    assert changed.version == 2
    assert all(item.status == "STALE" for item in [brief, proof, draft, review])
    with pytest.raises(ValueError):
        f.draft(w.id, q["id"], doc(e))


def test_discard_removes_current_and_historical_emphasis_and_cannot_reactivate(flow):
    f, w, e, q = setup(flow)
    original = edit(f, w, q, emphasis_state="active", emphasis="폐기할 방향")
    deleted = edit(f, w, q, emphasis_state="discarded")
    assert "폐기할 방향" not in str(original.data)
    assert context(deleted)["emphasis"] is None
    assert "폐기할 방향" not in str(deleted.data)
    with pytest.raises(ValueError, match="폐기"):
        edit(f, w, q, emphasis_state="active", emphasis="복원 시도")


def test_guide_version_drift_blocks_generation_until_redesign(flow, monkeypatch):
    from career import writing_plans
    f, w, e, q = setup(flow)
    f.question_brief(w.id, q["id"], {
        "question_id": q["id"], "question_type": "JOB_COMPETENCY", "evaluation_intent": "검증",
        "primary_message": "평가를 검증했습니다.", "evidence_ids": [e.id]})
    verify_claim(f, w, q["id"])
    f.approve_question(w.id, q["id"])
    original = writing_plans.guide_for
    def newer(*args):
        guide = original(*args)
        return {**guide, "label": "갱신된 가이드"}
    monkeypatch.setattr(writing_plans, "guide_for", newer)
    assert not public_preview(f, w.id, q["id"])["plan_current"]
    with pytest.raises(ValueError, match="작성 설계"):
        f.draft(w.id, q["id"], doc(e))


def test_other_user_cannot_read_or_change_plan(flow):
    from career.workflow import Workflow
    f, w, e, q = setup(flow)
    other = Workflow(f.db, "other")
    with pytest.raises(LookupError):
        public_preview(other, w.id, q["id"])
    with pytest.raises(LookupError):
        persist(other, w.id, q["id"])


def test_schema_rejects_client_injected_guides_and_facts(flow):
    from pydantic import ValidationError
    f, w, e, q = setup(flow)
    state = public_preview(f, w.id, q["id"])
    with pytest.raises(ValidationError):
        PlanRequest.model_validate({"expected_revision": state["state_revision"], "guide": {"fake": True}})

