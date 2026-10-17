from copy import deepcopy

import pytest
from career.final_decision import confirm, context, inputs, require_pass
from career.models import Fact
from career.workflow import Workflow
from final_review_fixture import confirm_final, final_payload
from sqlalchemy import func, select
from test_api import client  # noqa: F401
from test_workflow import doc, finish, flow, verify_claim  # noqa: F401


def test_final_questions_block_ready_and_chat_then_preserve_user_answers_in_bundle(flow):  # noqa: F811
    f, w, e = flow
    q = finish(f, w, e)
    with pytest.raises(ValueError, match="마지막 세 질문"):
        f.ready(w.id)
    from career.application_packet import packet_status

    assert not next(c for c in packet_status(f.db, "a", w.id)["checklist"] if c["code"] == "final_questions")["complete"]
    with pytest.raises(ValueError, match="마지막 세 질문"):
        f.command(w.id, "ㄱㄱ", q["id"])
    before = f.db.scalar(select(func.count()).select_from(Fact))
    result = confirm_final(f, w.id)
    assert next(c for c in packet_status(f.db, "a", w.id)["checklist"] if c["code"] == "final_questions")["complete"]
    assert w.state == "REVIEWING" and result.status == "LOCKED"
    assert f.db.scalar(select(func.count()).select_from(Fact)) == before
    f.ready(w.id)
    bundle = f.freeze(w.id)
    saved = next(a for a in bundle.data["artifacts"] if a["kind"] == "FinalSubmissionReview")
    assert saved["data"]["motivation_answer"] == result.data["motivation_answer"]
    handoff = f.handoff(w.id)
    assert handoff.data["final_questions"][0]["motivation_answer"] == result.data["motivation_answer"]
    assert handoff.data["final_questions"][0]["fact_authority"] is False
    old = deepcopy(bundle.data)
    with pytest.raises(ValueError, match="제출 보관본"):
        confirm(f, w.id, final_payload(f, w.id))
    assert bundle.data == old and w.state == "SUBMISSION_FROZEN"


@pytest.mark.parametrize("change", [
    {"confirmed": False}, {"confirmed": "true"}, {"role_noun": "다른 직업"},
    {"role_alignment": "MISMATCH"}, {"wants_core_work": False}, {"wants_core_work": "true"},
    {"context_hash": "old"}, {"motivation_answer": " " * 30}, {"return_stage": "STRATEGY"},
    {"citations": [{"evidence_id": "other-owner", "quote": "무관한 경험 원문"}]},
])
def test_explicit_current_concrete_final_answers_required(flow, change):  # noqa: F811
    f, w, e = flow
    finish(f, w, e)
    with pytest.raises(ValueError):
        confirm(f, w.id, {**final_payload(f, w.id), **change})
    assert not context(f, w.id)["current_pass"]


def test_revision_decision_is_recorded_with_return_stage_and_blocks_ready(flow):  # noqa: F811
    f, w, e = flow
    finish(f, w, e)
    result = confirm(f, w.id, {**final_payload(f, w.id), "wants_core_work": False,
                            "role_alignment": "UNCERTAIN", "decision": "REVISE", "return_stage": "STRATEGY"})
    assert result.data["return_stage"] == "STRATEGY" and w.state == "NEED_USER_ACTION"
    with pytest.raises(ValueError):
        f.ready(w.id)
    approved = confirm_final(f, w.id)
    assert result.status == "SUPERSEDED" and approved.version == 2
    assert confirm_final(f, w.id).id == approved.id


def test_new_document_evidence_change_and_new_question_require_reconfirmation(flow):  # noqa: F811
    f, w, e = flow
    q = finish(f, w, e)
    old = final_payload(f, w.id)
    confirmation = confirm_final(f, w.id)
    e.data = {**e.data, "scope_note": "prototype only"}
    with pytest.raises(ValueError, match="바뀌"):
        require_pass(f, w.id)
    confirm_final(f, w.id)
    with pytest.raises(ValueError, match="작성 설계가 바뀌"):
        f.draft(w.id, q["id"], doc(e))
    brief = f.artifact(w.id, "QuestionBrief", q["id"])
    f.question_brief(w.id, q["id"], brief.data)
    verify_claim(f, w, q["id"])
    f.approve_question(w.id, q["id"])
    f.draft(w.id, q["id"], doc(e))
    assert confirmation.status == "SUPERSEDED"
    with pytest.raises(ValueError):
        confirm(f, w.id, old)
    f.review(w.id, q["id"], manual_verified=True)
    f.final_lock(w.id, q["id"])
    confirm_final(f, w.id)
    f.add_question(w.id, "협업 경험을 알려 주세요", 1000)
    with pytest.raises(ValueError):
        require_pass(f, w.id)


def test_final_answers_only_visible_to_owner_and_resume_only_supported(flow):  # noqa: F811
    f, w, e = flow
    f.approve_strategy(w.id)
    f.resume(w.id, doc(e))
    f.review(w.id, resume=True, manual_verified=True)
    f.final_lock(w.id, resume=True)
    confirm_final(f, w.id)
    assert context(f, w.id)["current_pass"]
    f.ready(w.id)
    with pytest.raises(LookupError):
        inputs(Workflow(f.db, "b"), w.id)


def test_final_review_http_current_versions_and_request_isolation(client, monkeypatch):  # noqa: F811
    import json

    from career.api import app, database

    generator = app.dependency_overrides[database]()
    db = next(generator)
    f, w, e = getattr(flow, "__wrapped__")(db)
    finish(f, w, e)
    wid = w.id
    db.commit()
    generator.close()
    monkeypatch.setenv("AUTH_TOKENS", json.dumps({"alice-key": "a", "bob-key": "b"}))
    client.headers["Authorization"] = "Bearer alice-key"
    root = f"/api/applications/{wid}"
    received = client.get(root + "/final-review-context")
    assert received.status_code == 200
    generator = app.dependency_overrides[database]()
    db = next(generator)
    payload = final_payload(Workflow(db, "a"), wid)
    generator.close()
    response = client.post(root + "/actions/final-review", json=payload, headers={"Idempotency-Key": "final-review-once"})
    assert response.status_code == 200, response.text
    assert client.get(root + "/final-review-context").json()["current_pass"]
    assert client.post(root + "/actions/ready", json={}).status_code == 200
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get(root + "/final-review-context").status_code == 404
    assert client.post(root + "/actions/final-review", json=payload).status_code == 404
