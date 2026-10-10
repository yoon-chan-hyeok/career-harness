# ruff: noqa: F811 -- shared workflow fixture
from copy import deepcopy

import pytest
from career.providers import FakeLLMProvider
from career.truth import add_evidence, register_source
from test_workflow import doc, flow, proof_payload, question, verify_claim  # noqa: F401


def setup(flow, message="평가 실험을 검증했습니다."):
    service, workspace, evidence = flow
    service.approve_strategy(workspace.id)
    q = question(service, workspace, evidence, message, tested=False)
    brief = service.artifact(workspace.id, "QuestionBrief", q["id"])
    return service, workspace, evidence, q, brief


def test_approval_requires_completed_current_evidence_test(flow):
    f, w, e, q, brief = setup(flow)
    with pytest.raises(ValueError, match="Evidence Test"):
        f.approve_question(w.id, q["id"])
    proof = f.test_claim(w.id, q["id"], proof_payload(brief.data, e), confirmed=True)
    assert brief.status == "ACTIVE" and proof.data["result"] == "PASSED"
    assert proof.data["mode"] == "USER_VERIFIED"
    f.approve_question(w.id, q["id"])
    assert proof.status == "LOCKED"
    draft = f.draft(w.id, q["id"], doc(e))
    assert proof.id in draft.depends_on


@pytest.mark.parametrize("message", ["매출 999%를 달성했습니다.", "전체 시스템 개발"])
def test_manual_or_model_pass_labels_cannot_override_hard_evidence_checks(flow, message):
    f, w, e, q, brief = setup(flow, message)
    proof = f.test_claim(w.id, q["id"], proof_payload(brief.data, e), confirmed=True)
    assert proof.data["result"] == "NEEDS_REVISION" and proof.data["hard_issues"]
    with pytest.raises(ValueError, match="Evidence Test"):
        f.approve_question(w.id, q["id"])


def test_unsupported_semantic_claim_blocks_even_with_valid_evidence_id(flow):
    f, w, e, q, brief = setup(flow, "검증 제품을 고객사에 운영 배포했습니다.")
    data = proof_payload(brief.data, e)
    data["claims"][0].update(support="UNSUPPORTED", rationale="원문에는 실험만 있고 고객사 운영 기록은 없음")
    data["checks"][0]["verdict"] = "FAIL"
    f.provider = FakeLLMProvider({"claim_evidence_test": data})
    proof = f.test_claim(w.id, q["id"])
    assert proof.data["mode"] == "AI_REVIEWED"
    with pytest.raises(ValueError, match="Evidence Test"):
        f.approve_question(w.id, q["id"])


def test_exact_selected_citations_complete_checks_and_explicit_manual_confirmation(flow):
    f, w, e, q, brief = setup(flow)
    data = proof_payload(brief.data, e)
    with pytest.raises(ValueError, match="직접 대조"):
        f.test_claim(w.id, q["id"], data)
    source, _ = register_source(f.db, "other", "secret", "비공개 기록", "RAW_RESULT")
    private = add_evidence(f.db, "other", source.id, "secret", "비공개 기록", {}, "VERIFIED")
    for wrong in ["wrong", private.id]:
        invalid = deepcopy(data)
        invalid["claims"][0]["citations"][0]["evidence_id"] = wrong
        with pytest.raises(ValueError, match="선택한 근거"):
            f.test_claim(w.id, q["id"], invalid, confirmed=True)
    invalid = deepcopy(data)
    invalid["claims"][0]["citations"][0]["quote"] = "원문에 없는 성공 사례"
    with pytest.raises(ValueError, match="정확히 일치"):
        f.test_claim(w.id, q["id"], invalid, confirmed=True)
    invalid = deepcopy(data)
    invalid["checks"][0] = deepcopy(invalid["checks"][1])
    with pytest.raises(ValueError, match="네 가지"):
        f.test_claim(w.id, q["id"], invalid, confirmed=True)


def test_evidence_test_covers_supporting_claims_not_just_primary(flow):
    f, w, e, q, brief = setup(flow)
    second = f.question_brief(w.id, q["id"], {**brief.data, "supporting_claims": ["평가를 설계했습니다."]})
    with pytest.raises(ValueError, match="빠짐없이"):
        f.test_claim(w.id, q["id"], proof_payload(brief.data, e), confirmed=True)
    data = proof_payload(second.data, e)
    data["followups"] = ["판단을 바꾼 근거를 확인해야 함"]
    proof = f.test_claim(w.id, q["id"], data, confirmed=True)
    assert proof.data["result"] == "NEEDS_REVISION"


def test_changed_claim_or_failed_retest_invalidates_proof_and_generated_document(flow):
    f, w, e, q, brief = setup(flow)
    proof = verify_claim(f, w, q["id"])
    f.approve_question(w.id, q["id"])
    draft = f.draft(w.id, q["id"], doc(e))
    failed = proof_payload(brief.data, e)
    failed["checks"][0]["verdict"] = "FAIL"
    f.test_claim(w.id, q["id"], failed, confirmed=True)
    assert proof.status == "SUPERSEDED" and draft.status == "STALE"
    with pytest.raises(ValueError, match="Evidence Test"):
        f.draft(w.id, q["id"], doc(e))
    f.question_brief(w.id, q["id"], {**brief.data, "primary_message": "평가를 직접 설계했습니다."})
    with pytest.raises(ValueError):
        f.approve_question(w.id, q["id"])


def test_go_next_runs_only_test_then_waits_for_user_approval(flow):
    f, w, e, q, brief = setup(flow)
    f.provider = FakeLLMProvider({"claim_evidence_test": proof_payload(brief.data, e)})
    result = f.command(w.id, "ㄱㄱ", q["id"])
    assert f.artifact(w.id, "ClaimEvidenceTest", q["id"]).id in result["patched_artifacts"]
    assert brief.status == "ACTIVE"
    with pytest.raises(ValueError, match="승인"):
        f.command(w.id, "ㄱㄱ", q["id"])
