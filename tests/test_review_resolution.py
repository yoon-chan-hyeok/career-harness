# ruff: noqa: F811 -- shared workflow fixture
from copy import deepcopy

import pytest
from career.artifacts import latest
from career.conversation import ChatRequest, converse
from career.providers import FakeLLMProvider
from career.references import compile_pack, register
from career.review_resolution import context
from career.workflow import Workflow
from test_api import client  # noqa: F401
from test_workflow import doc, flow, question  # noqa: F401


def prepared(flow, *, resume=False, extra=False, risk=None):
    f, w, e = flow
    f.approve_strategy(w.id)
    if resume:
        qid = ""
        f.resume(w.id, doc(e))
    else:
        qid = question(f, w, e)["id"]
        f.approve_question(w.id, qid)
        f.draft(w.id, qid, doc(e))
    captures = {}
    questions = [{"question": "본인이 직접 수행한 범위를 확인해 주세요.", "category": "GROUNDING"}]
    if extra:
        questions.append({"question": "본업을 하고 싶은 이유는 무엇인가요?", "category": "JOB_MOTIVATION"})

    class Capture:
        last_trace = {"model": "synthetic-review-resolution"}

        def structured(self, stage, data, schema):
            captures[stage] = deepcopy(data)
            return schema.model_validate({
                "issues": [risk] if risk and stage == "recruiter" else [],
                "followups": [row["question"] for row in questions] if stage == "reverse_interview" else [],
                "followup_details": questions if stage == "reverse_interview" else [],
            })

    f.provider = Capture()
    review = f.review(w.id, qid, resume=resume)
    return f, w, e, qid, review, captures


def answers(review, e, *, action="ANSWER_WITH_EVIDENCE"):
    return {"review_id": review.id, "review_version": review.version, "confirmed": True,
            "entries": [{"task_id": task["id"], "action": action, "answer": e.body,
                         "rationale": "현재 선택한 실험 기록과 개인 수행 범위를 직접 대조함",
                         "citations": [{"evidence_id": e.id, "quote": e.body}]}
                        for task in review.data["response_tasks"]]}


def test_reverse_receives_job_context_and_recruiter_stays_blind(flow):
    f, w, e, qid, review, captures = prepared(flow)
    reverse = captures["reverse_interview"]
    assert reverse["jd"] == w.jd_raw and reverse["opportunity"]["base_profession"] == "평가 연구원"
    assert reverse["strategy"]["assignment_statement"]
    assert reverse["question"] == f.question(w.id, qid)["text"]
    assert not {"evidence", "strategy", "canonical_profile"}.intersection(captures["recruiter"])


def test_unanswered_blocks_lock_and_quick_manual_review_cannot_erase_questions(flow):
    f, w, e, qid, review, _ = prepared(flow)
    with pytest.raises(ValueError, match="검수 질문"):
        f.final_lock(w.id, qid)
    again = f.review(w.id, qid, manual_verified=True)
    assert again.data["response_tasks"] == review.data["response_tasks"]
    with pytest.raises(ValueError, match="검수 질문"):
        f.final_lock(w.id, qid)


@pytest.mark.parametrize("resume", [False, True])
def test_answer_lock_and_frozen_handoff_preserve_user_words_without_promoting_truth(flow, resume):
    f, w, e, qid, review, _ = prepared(flow, resume=resume)
    before = deepcopy(e.data)
    response = f.answer_review(w.id, qid, answers(review, e), resume=resume, manual=True)
    assert response.kind == ("ResumeReviewResponses" if resume else "ReviewResponses")
    assert response.data["status"] == "RESOLVED" and response.data["fact_authority"] is False
    f.final_lock(w.id, qid, resume=resume)
    assert response.status == "LOCKED"
    f.provider = None
    from final_review_fixture import confirm_final

    confirm_final(f, w.id)
    f.ready(w.id)
    bundle = f.freeze(w.id)
    frozen = deepcopy(bundle.data)
    result = f.handoff(w.id)
    note = result.data["review_responses"][0]
    assert note["entries"][0]["answer"] == e.body and note["fact_authority"] is False
    assert note["response_artifact_id"] == response.id
    assert e.data == before and bundle.data == frozen
    with pytest.raises(ValueError):
        f.answer_review(w.id, qid, answers(review, e), resume=resume, manual=True)


def test_manual_response_requires_confirmation_and_exact_selected_quote(flow):
    f, w, e, qid, review, _ = prepared(flow)
    data = answers(review, e)
    data["confirmed"] = False
    with pytest.raises(ValueError, match="직접"):
        f.answer_review(w.id, qid, data, manual=True)
    data["confirmed"] = True
    data["entries"][0]["citations"][0]["quote"] = "등록된 원문에 없는 내용"
    with pytest.raises(ValueError, match="정확히 일치"):
        f.answer_review(w.id, qid, data, manual=True)
    data["entries"][0]["citations"][0].update(evidence_id="another-users-evidence", quote=e.body)
    with pytest.raises(ValueError, match="선택한 근거"):
        f.answer_review(w.id, qid, data, manual=True)


def test_grounding_cannot_be_waived_as_interview_preparation(flow):
    f, w, e, qid, review, _ = prepared(flow)
    with pytest.raises(ValueError, match="면접 대비"):
        f.answer_review(w.id, qid, answers(review, e, action="INTERVIEW_PREP"), manual=True)


@pytest.mark.parametrize("action", ["ADD_EVIDENCE", "REVISE_DOCUMENT"])
def test_promised_change_remains_unresolved_until_performed(flow, action):
    f, w, e, qid, review, _ = prepared(flow)
    result = f.answer_review(w.id, qid, answers(review, e, action=action), manual=True)
    assert result.data["status"] == "NEEDS_ACTION"
    with pytest.raises(ValueError, match="미해결"):
        f.final_lock(w.id, qid)


def test_rereview_invalidates_old_response(flow):
    f, w, e, qid, review, _ = prepared(flow)
    data = answers(review, e)
    result = f.answer_review(w.id, qid, data, manual=True)
    f.review(w.id, qid)
    assert result.status == "STALE"
    with pytest.raises(ValueError, match="검수 버전"):
        f.answer_review(w.id, qid, data, manual=True)
    with pytest.raises(ValueError):
        f.final_lock(w.id, qid)


@pytest.mark.parametrize("resume", [False, True])
def test_revision_disposition_preserves_approval_and_requires_new_version_review(flow, resume):
    from career.human_review import propose_patch, resolve

    f, w, e, qid, review, _ = prepared(flow, resume=resume)
    pending = f.answer_review(w.id, qid, answers(review, e, action="REVISE_DOCUMENT"),
                             resume=resume, manual=True)
    original = f.artifact(w.id, "ResumeContent" if resume else "Draft", qid)
    replacement = original.data["text"].replace("직접", "스스로")
    claims = [{**row, "text": replacement} for row in original.data["claims"]]
    proposal = propose_patch(f, w.id, qid, {
        "old_text": original.data["text"], "new_text": replacement,
        "claims": claims, "issue_codes": [],
    }, resume=resume, review_id=review.id)
    assert original.data["text"] == e.body and pending.data["status"] == "NEEDS_ACTION"
    with pytest.raises(ValueError, match="미해결"):
        f.final_lock(w.id, qid, resume=resume)
    result = resolve(f, w.id, proposal["id"], "ACCEPT")
    assert result["status"] == "ACCEPTED"
    assert original.data["text"] == e.body and review.status == pending.status == "STALE"
    revised = f.artifact(w.id, original.kind, qid)
    assert revised.data["text"] == replacement and revised.id != original.id
    with pytest.raises(ValueError):
        f.final_lock(w.id, qid, resume=resume)
    current_review = f.review(w.id, qid, resume=resume)
    with pytest.raises(ValueError):
        f.answer_review(w.id, qid, answers(review, e), resume=resume, manual=True)
    current_response = f.answer_review(w.id, qid, answers(current_review, e), resume=resume, manual=True)
    f.final_lock(w.id, qid, resume=resume)
    assert current_response.status == revised.status == "LOCKED"
    assert current_response.data["document_id"] == revised.id and pending.status == "SUPERSEDED"


def test_partial_answers_keep_other_results_and_new_response_requires_relocking(flow):
    f, w, e, qid, review, _ = prepared(flow, extra=True)
    data = answers(review, e)
    first = f.answer_review(w.id, qid, {**data, "entries": data["entries"][:1]}, manual=True)
    assert first.data["status"] == "NEEDS_ACTION" and len(first.data["unanswered_task_ids"]) == 1
    second_entry = {**data["entries"][1], "action": "INTERVIEW_PREP", "citations": [],
                    "answer": "평가 업무 자체에 관심이 있고 기본 실험부터 배우고 싶습니다."}
    second = f.answer_review(w.id, qid, {**data, "entries": [second_entry]}, manual=True)
    assert second.data["entries"][0] == first.data["entries"][0]
    assert second.data["status"] == "RESOLVED" and second.data["unanswered_task_ids"] == []
    locked = f.final_lock(w.id, qid)
    f.answer_review(w.id, qid, {**data, "entries": [second_entry]}, manual=True)
    assert locked.status == "ACTIVE"
    with pytest.raises(ValueError, match="최종 잠금"):
        f.ready(w.id)
    f.final_lock(w.id, qid)


def test_ai_negative_verdict_blocks_even_with_exact_quote(flow):
    f, w, e, qid, review, _ = prepared(flow)
    f.provider = FakeLLMProvider({"review_answers": {"items": [
        {"task_id": review.data["response_tasks"][0]["id"], "verdict": "NEEDS_EVIDENCE",
         "rationale": "인용문은 질문의 구체적인 범위를 증명하지 않음"}]}})
    result = f.answer_review(w.id, qid, answers(review, e))
    assert result.data["status"] == "NEEDS_ACTION"
    with pytest.raises(ValueError, match="미해결"):
        f.final_lock(w.id, qid)


def test_response_context_is_owner_scoped(flow):
    f, w, e, qid, _, _ = prepared(flow)
    with pytest.raises(LookupError):
        context(Workflow(f.db, "unrelated"), w.id, qid)


@pytest.mark.parametrize("priority", ["P1", "P2"])
def test_recruiter_risk_disposition_cannot_waive_major_issue(flow, priority):
    f, w, e, qid, review, _ = prepared(flow, risk={
        "code": "VISIBLE_SCOPE", "priority": priority, "message": "실제 업무 경험 범위를 확인해야 함"})
    data = answers(review, e)
    risk = next(entry for entry in data["entries"] if entry["task_id"] == review.data["response_tasks"][0]["id"])
    risk.update(action="ACKNOWLEDGE_GAP", answer="실제 운영 경험은 없으며 실험 범위에서 설명하겠습니다.", citations=[])
    result = f.answer_review(w.id, qid, data, manual=True)
    assert result.data["status"] == ("NEEDS_ACTION" if priority == "P1" else "RESOLVED")
    if priority == "P1":
        with pytest.raises(ValueError, match="중대한"):
            f.final_lock(w.id, qid)


@pytest.mark.parametrize("stage", ["reverse_interview", "review_answers", "review_answer_extract", "interview_handoff"])
def test_resume_response_roles_use_resume_rules_without_cover_templates(db, stage):
    register(db, "a", "cover", "# 8. Review\nCover criteria.")
    register(db, "a", "resume", "# 7. Resume\nResume-specific criteria.")
    keys = {r["key"] for r in compile_pack(db, "a", stage, "RESUME")["references"]}
    assert "resume" in keys and "cover" not in keys


@pytest.mark.parametrize("invented", [False, True])
def test_conversation_records_exact_user_words_never_invents_answer_or_approval(flow, invented):
    f, w, e, qid, review, _ = prepared(flow)
    entry = answers(review, e)["entries"][0]
    if invented:
        entry["answer"] = "사용자가 말한 적 없는 답변"
    f.provider = FakeLLMProvider({
        "conversation_router": {"reply": "", "action": "review-answers"},
        "review_answer_extract": {"entries": [entry], "clarification": ""},
        "review_answers": {"items": [{"task_id": entry["task_id"], "verdict": "RESOLVED", "rationale": "현재 수행 기록과 일치함"}]},
    })
    request = ChatRequest(text="첫 질문은 현재 근거로 답할게요. " + e.body,
                          client_id="review-answer-synthetic", question_id=qid, artifact_id=review.id)
    turn = converse(f, w.id, request)
    result = latest(f.db, f.user, w.id, "ReviewResponses", qid, required=False)
    if invented:
        assert turn["data"]["response"]["status"] == "NEEDS_INPUT" and result is None
    else:
        assert result and result.data["entries"][0]["answer"] == e.body
        assert result.data["mode"] == "AI_REVIEWED" and result.status == "ACTIVE"
        assert f.artifact(w.id, "Draft", qid).status == "ACTIVE"
        assert converse(f, w.id, request)["id"] == turn["id"]


def test_http_response_context_isolation_version_validation_and_retry(client, monkeypatch):
    import json

    from career.api import app, database

    monkeypatch.setenv("AUTH_TOKENS", json.dumps({"a-test-key": "a", "b-test-key": "b"}))
    generator = app.dependency_overrides[database]()
    db = next(generator)
    f, w, e, qid, review, _ = prepared(getattr(flow, "__wrapped__")(db))
    payload = answers(review, e)
    workspace_id, review_id, review_version = w.id, review.id, review.version
    db.commit()
    generator.close()
    client.headers["Authorization"] = "Bearer a-test-key"
    path = f"/api/applications/{workspace_id}"
    result = client.get(f"{path}/review-response-context", params={"qid": qid})
    assert result.status_code == 200 and result.json()["review_id"] == review_id
    wrong = {**payload, "review_version": review_version + 1}
    invalid = client.post(path + "/actions/review-answers", json={"qid": qid, "responses": wrong, "manual_verified": True})
    assert invalid.status_code == 409
    body = {"qid": qid, "responses": payload, "manual_verified": True}
    first = client.post(path + "/actions/review-answers", json=body, headers={"Idempotency-Key": "review-response-retry"})
    assert first.status_code == 200, first.text
    assert first.json()["data"]["status"] == "RESOLVED"
    assert client.post(path + "/actions/review-answers", json=body,
                       headers={"Idempotency-Key": "review-response-retry"}).json()["id"] == first.json()["id"]
    client.headers["Authorization"] = "Bearer b-test-key"
    assert client.get(f"{path}/review-response-context", params={"qid": qid}).status_code == 404
    assert client.post(path + "/actions/review-answers", json=body).status_code == 404
