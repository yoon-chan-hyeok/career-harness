from copy import deepcopy

import pytest
from career.providers import ProviderUnavailable
from career.truth import add_evidence, register_source
from career.workflow import Workflow


@pytest.fixture
def flow(db):
    source, _ = register_source(
        db, "a", "results", "직접 실험을 설계하고 정확도 80%를 확인했습니다.", "RAW_RESULT"
    )
    e = add_evidence(
        db,
        "a",
        source.id,
        "RAG 평가",
        "직접 실험을 설계하고 정확도 80%를 확인했습니다.",
        {"ownership": {"implementation": "USER"}, "forbidden_claims": ["전체 시스템 개발"]},
        "VERIFIED",
    )
    f = Workflow(db, "a")
    w = f.create("예시회사", "평가 연구원", "모델 평가 보고서를 작성합니다.")
    f.analyze(w.id, {"actual_outputs": ["평가 보고서"], "base_profession": "평가 연구원"})
    f.map_evidence(
        w.id,
        {
            "items": [
                {
                    "evidence_id": e.id,
                    "job_output_id": "평가 보고서",
                    "classification": "DIRECT",
                    "evidence_strength": "STRONG",
                    "ownership_strength": "STRONG",
                    "rationale": "실험 설계",
                }
            ],
            "uncovered_outputs": [],
        },
    )
    f.strategy(
        w.id,
        {
            "positioning": "평가 연구원",
            "base_profession_identity": "연구원",
            "main_skill_message": "실험 검증",
            "assignment_statement": "평가 실험을 설계하고 결과를 확인합니다.",
        },
    )
    return f, w, e


def question(f, w, e, message="평가 실험을 검증했습니다."):
    q = f.add_question(w.id, "직무 역량을 설명하세요.", 1000)
    f.question_brief(
        w.id,
        q["id"],
        {
            "question_id": q["id"],
            "question_type": "JOB_COMPETENCY",
            "evaluation_intent": "검증",
            "primary_message": message,
            "evidence_ids": [e.id],
        },
    )
    return q


def doc(e):
    return {
        "text": e.body,
        "claims": [
            {
                "text": e.body,
                "type": "METRIC",
                "evidence_ids": [e.id],
                "support": "SUPPORTED",
                "ownership_ok": True,
            }
        ],
    }


def finish(f, w, e):
    f.approve_strategy(w.id)
    q = question(f, w, e)
    f.approve_question(w.id, q["id"])
    f.draft(w.id, q["id"], doc(e))
    f.review(w.id, q["id"], manual_verified=True)
    f.final_lock(w.id, q["id"])
    return q


def test_personal_e2e_freeze_is_not_submission_and_handoff_immutable(flow, db):
    f, w, e = flow
    finish(f, w, e)
    f.resume(w.id, doc(e))
    f.review(w.id, resume=True, manual_verified=True)
    f.final_lock(w.id, resume=True)
    f.ready(w.id)
    bundle = f.freeze(w.id)
    snapshot = deepcopy(bundle.data)
    assert w.state == "SUBMISSION_FROZEN"
    assert bundle.data["submitted_at"] is None
    first = f.handoff(w.id)
    second = f.handoff(w.id)
    assert first.id != second.id
    assert second.depends_on == [bundle.id]
    assert bundle.data == snapshot
    with pytest.raises(ValueError):
        f.confirm_submission(w.id, False)
    f.confirm_submission(w.id, True)
    assert w.state == "SUBMITTED" and w.data["submitted_at"]
    assert bundle.data == snapshot
    db.commit()
    assert Workflow(db, "a").ws(w.id).state == "SUBMITTED"


def test_guided_commands_cannot_skip_approvals(flow):
    f, w, e = flow
    with pytest.raises(ValueError, match="전략"):
        f.command(w.id, "ㄱㄱ")
    with pytest.raises(ValueError):
        question(f, w, e)
    f.approve_strategy(w.id)
    q = question(f, w, e)
    with pytest.raises(ValueError):
        f.draft(w.id, q["id"], doc(e))
    with pytest.raises(ValueError, match="승인"):
        f.command(w.id, "ㄱㄱ", q["id"])


def test_edit_locked_brief_creates_version_and_stales_draft(flow):
    f, w, e = flow
    q = finish(f, w, e)
    old = f.artifact(w.id, "QuestionBrief", q["id"])
    draft = f.artifact(w.id, "Draft", q["id"])
    f.question_brief(w.id, q["id"], {**old.data, "primary_message": "새로운 메시지"})
    assert old.status == "SUPERSEDED"
    assert f.artifact(w.id, "QuestionBrief", q["id"]).version == 2
    assert draft.status == "STALE"
    with pytest.raises(ValueError):
        f.ready(w.id)


def test_metric_correction_stales_resume_and_cover_letter_but_preserves_frozen(flow):
    f, w, e = flow
    finish(f, w, e)
    f.resume(w.id, doc(e))
    f.review(w.id, resume=True, manual_verified=True)
    f.final_lock(w.id, resume=True)
    f.ready(w.id)
    bundle = f.freeze(w.id)
    original = deepcopy(bundle.data)
    result = f.command(w.id, "이 수치 틀림", evidence_id=e.id)
    assert result["stale_artifacts"]
    assert bundle.data == original and bundle.status == "LOCKED"
    with pytest.raises(ValueError):
        f.artifact(w.id, "ResumeContent")


def test_protected_span_and_patch_requires_revalidation(flow):
    f, w, e = flow
    q = finish(f, w, e)
    f.patch_document(w.id, q["id"], "", "", protected=["80%"])
    with pytest.raises(ValueError, match="보호"):
        f.patch_document(w.id, q["id"], "80%", "90%")
    f.patch_document(w.id, q["id"], "직접", "스스로")
    review = f.review(w.id, q["id"], manual_verified=True)
    assert any(i["code"] == "CLAIM_SUPPORT" for i in review.data["issues"])
    with pytest.raises(ValueError):
        f.final_lock(w.id, q["id"])


def test_outcome_attribution_and_cross_user(flow, db):
    f, w, _ = flow
    f.outcome(w.id, "CODING_FAIL")
    result = f.postmortem(w.id)
    assert result.data["attribution_scope"] == "CODING"
    assert not result.data["writing_rule_updated"]
    with pytest.raises(LookupError):
        Workflow(db, "b").ws(w.id)


def test_provider_failure_does_not_advance_state(flow):
    f, w, _ = flow
    state = w.state

    class Broken:
        def structured(self, *args):
            raise ProviderUnavailable("offline")

    f.provider = Broken()
    with pytest.raises(ProviderUnavailable):
        f.strategy(w.id)
    assert w.state == state


def test_opportunity_rejects_candidate_fields(flow):
    f, w, _ = flow
    with pytest.raises(ValueError):
        f.analyze(w.id, {"actual_outputs": ["보고서"], "base_profession": "연구원", "fatal_gaps": ["gap"]})


def test_unsupported_metric_blocks_final_lock(flow):
    f, w, e = flow
    f.approve_strategy(w.id)
    q = question(f, w, e)
    f.approve_question(w.id, q["id"])
    bad = doc(e)
    bad["text"] = "정확도 99%"
    bad["claims"][0]["text"] = bad["text"]
    f.draft(w.id, q["id"], bad)
    f.review(w.id, q["id"], manual_verified=True)
    with pytest.raises(ValueError):
        f.final_lock(w.id, q["id"])
