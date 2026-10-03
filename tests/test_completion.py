# Imported pytest fixtures are intentionally used as function parameters.
# ruff: noqa: F811
import json

import httpx
import pytest
from career.conversation import ChatRequest, converse, history
from career.decisions import JevDecisionProvider
from career.domain import save_entity
from career.entities import OwnershipRecord, WritingRuleRecord
from career.extraction import apply, propose
from career.projections import ApplicationQuestion, CorrectionRecord, SubmissionSnapshot
from career.providers import FakeLLMProvider
from career.resume import HTMLRenderer, ResumeContent, legacy_sections
from career.truth import invalidate_source
from career.validation import hard_qa
from career.workflow import Workflow
from sqlalchemy import select
from test_workflow import doc, finish, flow  # noqa: F401


def test_resume_chat_lock_targets_resume(flow):
    f, w, e = flow
    finish(f, w, e)
    resume = f.resume(w.id, doc(e))
    f.review(w.id, resume=True, manual_verified=True)
    turn = converse(f, w.id, ChatRequest(text="잠가", client_id="resume-lock-123", artifact_id=resume.id))
    assert turn["data"]["response"]["status"] == "OK"
    assert resume.status == "LOCKED"


def test_old_chat_document_cannot_approve_current_version(flow):
    f, w, e = flow
    q = finish(f, w, e)
    old = f.artifact(w.id, "QuestionBrief", q["id"])
    new = f.question_brief(w.id, q["id"], {**old.data, "primary_message": "새 판단"})
    turn = converse(
        f,
        w.id,
        ChatRequest(
            text="이걸로 가자", client_id="old-approval-123", question_id=q["id"], artifact_id=old.id
        ),
    )
    assert turn["data"]["response"]["status"] == "NEEDS_INPUT"
    assert new.status == "ACTIVE"


def test_document_outcome_persists_candidate_only(flow, db):
    f, w, _ = flow
    f.outcome(w.id, "DOCUMENT_FAIL", "근거 범위가 잘 보이지 않음")
    p = f.postmortem(w.id)
    candidate = db.get(WritingRuleRecord, p.data["candidate_rule_ids"][0])
    assert candidate.status == "CANDIDATE" and candidate.data["scope_type"] == "COMPANY"
    f.postmortem(w.id)
    assert len(list(db.scalars(select(WritingRuleRecord)))) == 1
    f.outcome(w.id, "CODING_FAIL", "문제 풀이 부족")
    assert f.postmortem(w.id).data["candidate_rules"] == []


def test_evidence_correction_has_dedicated_provenance(flow, db):
    f, w, e = flow
    f.command(w.id, "이 수치 틀림", evidence_id=e.id)
    correction = db.scalar(select(CorrectionRecord))
    assert correction.evidence_id == e.id and correction.source_id == e.source_id


def test_resume_ledger_refresh_matches_structured_preview(flow):
    f, w, e = flow
    finish(f, w, e)
    f.resume(w.id, doc(e))
    updated = f.update_ledger(w.id, "", [{**doc(e)["claims"][0], "metric_ids": []}], resume=True)
    assert updated.data["sections"][0]["bullets"][0]["claims"] == updated.data["claims"]


def test_old_metric_is_blocked_after_confirmed_correction(flow):
    f, _, e = flow
    metric = {
        "source_id": e.source_id,
        "evidence_id": e.id,
        "name": "accuracy",
        "value": "80",
        "unit": "%",
        "dataset": "test",
        "subset": "heldout",
        "experiment_version": "v1",
        "baseline": None,
        "denominator": None,
        "valid_for_claims": [],
        "invalid_for_claims": [],
        "status": "USER_CONFIRMED",
    }
    save_entity(f.db, f.user, "Metric", metric, explicit_confirmation=True)
    save_entity(
        f.db,
        f.user,
        "Metric",
        {**metric, "value": "90", "experiment_version": "v2"},
        explicit_confirmation=True,
    )
    evidence = f.selected([e.id])
    assert any(i["code"] == "METRIC_CONFLICT" for i in hard_qa("정확도 80%", evidence))
    assert not hard_qa("정확도 90%", evidence)


def test_imported_claim_boundary_is_enforced():
    issues = hard_qa(
        "전체 시스템 개발",
        [
            {
                "body": "실험만 수행",
                "source_id": "s",
                "status": "VERIFIED",
                "data": {"claim_boundaries": ["전체 시스템 개발"]},
            }
        ],
    )
    assert any(i["code"] == "CLAIM_BOUNDARY" for i in issues)


def test_structured_provider_writing_review_resume_and_freeze(flow):
    f, w, e = flow
    f.approve_strategy(w.id)
    q = f.add_question(w.id, "문제 해결 경험", 1000)
    f.provider = FakeLLMProvider(
        {
            "question_brief": {
                "question_id": q["id"],
                "question_type": "CHALLENGE",
                "evaluation_intent": "판단",
                "primary_message": "실험 기준을 확인했다",
                "evidence_ids": [e.id],
            },
            "writer": doc(e),
            "fact_reviewer": {"issues": [], "followups": []},
            "recruiter": {"issues": [], "followups": []},
            "reverse_interview": {"issues": [], "followups": []},
            "resume_writer": legacy_sections(doc(e)),
            "cross_document_consistency": {"issues": [], "followups": []},
        }
    )
    f.question_brief(w.id, q["id"])
    f.approve_question(w.id, q["id"])
    draft = f.draft(w.id, q["id"])
    assert draft.model_version == "fake-test-only"
    f.review(w.id, q["id"])
    f.final_lock(w.id, q["id"])
    resume = f.resume(w.id)
    assert resume.data["sections"][0]["bullets"][0]["evidence_ids"] == [e.id]
    f.review(w.id, resume=True)
    f.final_lock(w.id, resume=True)
    f.ready(w.id)
    assert f.freeze(w.id).data["submitted_at"] is None


def test_candidate_and_other_company_rules_do_not_enter_writer_context(flow):
    from career.rules import writing_rules
    from career.truth import register_source

    f, w, e = flow
    source, _ = register_source(f.db, f.user, "writing-guidance", "평가 기준", "MASTER")
    payload = {
        "source_id": source.id,
        "scope_type": "COMPANY",
        "scope_value": w.company,
        "rule_type": "STYLE",
        "rule": "판단을 앞에 배치",
        "status": "CANDIDATE",
    }
    save_entity(f.db, f.user, "WritingRule", payload)
    assert writing_rules(f.db, f.user, w) == []
    from career.promotion import direct_preference

    active_data = direct_preference(f.db, f.user, payload["rule"], "COMPANY", w.company, confirmed=True)
    active = f.db.get(WritingRuleRecord, active_data["id"])
    assert active is not None
    assert len(writing_rules(f.db, f.user, w)) == 1
    assert active.data["origin"] == "USER_DIRECTIVE"
    direct_preference(f.db, f.user, payload["rule"], "COMPANY", "다른 회사", confirmed=True)
    assert len(writing_rules(f.db, f.user, w)) == 1


def test_chat_idempotency_and_isolation(flow, db):
    f, w, _ = flow
    req = ChatRequest(text="문항 추가: 지원 동기", client_id="message-123")
    first = converse(f, w.id, req)
    assert converse(f, w.id, req)["id"] == first["id"]
    assert len(w.data["questions"]) == 1
    assert db.get(ApplicationQuestion, w.data["questions"][0]["id"]) is not None
    with pytest.raises(LookupError):
        history(Workflow(db, "b"), w.id)
    with pytest.raises(ValueError):
        converse(f, w.id, ChatRequest(text="문항 추가: 다른 질문", client_id=req.client_id))


def test_chat_failure_preserves_state_and_does_not_approve(flow):
    f, w, _ = flow
    before = w.state
    answer = converse(f, w.id, ChatRequest(text="ㄱㄱ", client_id="message-123"))
    assert answer["data"]["response"]["status"] == "NEEDS_INPUT"
    assert w.state == before
    assert f.artifact(w.id, "ApplicationBrief").status != "LOCKED"


def test_chat_model_cannot_bypass_claim_gate(flow):
    f, w, _ = flow
    f.provider = FakeLLMProvider({"conversation_router": {"reply": "", "action": "generate"}})
    answer = converse(f, w.id, ChatRequest(text="본문 써", client_id="message-123"))
    assert answer["data"]["response"]["status"] == "NEEDS_INPUT"
    assert answer["data"]["response"]["artifact_ids"] == []


def test_extraction_exact_quote_and_confirmation(flow, db):
    f, _, e = flow
    payload = {
        "items": [
            {
                "kind": "Ownership",
                "quote": "직접 실험을 설계",
                "payload_json": json.dumps({"implementation": "USER"}),
            }
        ],
        "missing_information": [],
    }
    p = propose(f, e.id, payload)
    with pytest.raises(ValueError):
        apply(f, p["id"], False)
    ids = apply(f, p["id"], True)
    assert apply(f, p["id"], True) == ids
    assert db.get(OwnershipRecord, ids[0]).status == "USER_CONFIRMED"
    invalidate_source(db, "a", e.source_id, delete_content=True)
    assert db.get(OwnershipRecord, ids[0]).data == {}
    payload["items"][0]["quote"] = "원자료에 없는 문장"
    with pytest.raises(ValueError):
        propose(f, e.id, payload)


def test_snapshot_content_stays_immutable_on_submission(flow, db):
    f, w, e = flow
    finish(f, w, e)
    f.ready(w.id)
    bundle = f.freeze(w.id)
    snapshot = db.scalar(select(SubmissionSnapshot).where(SubmissionSnapshot.artifact_id == bundle.id))
    assert snapshot.submitted_at is None
    original = json.dumps(snapshot.content, sort_keys=True)
    f.confirm_submission(w.id, True)
    assert snapshot.submitted_at is not None
    assert json.dumps(snapshot.content, sort_keys=True) == original


def test_html_preview_escapes_user_markup(flow):
    _, _, e = flow
    data = doc(e)
    data["text"] = '<script>alert("private")</script>'
    data["claims"][0]["text"] = data["text"]
    rendered = HTMLRenderer().render(ResumeContent.model_validate(legacy_sections(data)))
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_jev_official_request_shape(monkeypatch):
    captured = []
    original_client = httpx.Client

    def handler(request):
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "answers": {"decision": {"choice": "yes", "confidence": 0.9}},
                "usage": {"input_tokens": 10},
            },
        )

    monkeypatch.setenv("JEV_API_KEY", "fixture-key")
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw)
    )
    provider = JevDecisionProvider()
    assert provider.binary("direct_answer", {"question": "a", "draft": "b"})
    assert captured[0]["questions"]["decision"]["type"] == "choice"
    assert provider.last_trace["usage"]["input_tokens"] == 10
