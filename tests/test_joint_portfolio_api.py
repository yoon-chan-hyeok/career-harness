# ruff: noqa: F811 -- reusable authenticated HTTP fixture
from contextlib import contextmanager

import pytest
from career.api import app, database
from career.models import Artifact, PromptRun, Source
from career.provider_policy import BudgetExceeded
from career.truth import add_evidence, register_source
from career.workflow import Workflow
from sqlalchemy import select
from test_api import client  # noqa: F401


@pytest.fixture
def http_joint(client, monkeypatch):
    monkeypatch.setenv("CAREER_JOINT_PORTFOLIO_ENABLED", "1")
    client.headers["Authorization"] = "Bearer alice-key"
    generator = app.dependency_overrides[database]()
    db = next(generator)
    f = Workflow(db, "alice")
    source, _ = register_source(db, "alice", "synthetic-results", "평가 기준을 설계했습니다.", "RAW_RESULT")
    e = add_evidence(db, "alice", source.id, "평가 실험", "평가 기준을 설계했습니다.",
                     {"ownership": {"implementation": "USER"}}, "VERIFIED")
    w = f.create("합성회사", "연구원", "평가 보고서 작성")
    f.analyze(w.id, {"actual_outputs": ["평가 보고서"], "base_profession": "연구원"})
    f.map_evidence(w.id, {"items": [{"evidence_id": e.id, "job_output_id": "평가 보고서", "classification": "DIRECT",
        "evidence_strength": "STRONG", "ownership_strength": "STRONG", "rationale": "확인된 실험"}], "uncovered_outputs": []})
    f.strategy(w.id, {"positioning": "평가 연구원", "base_profession_identity": "연구원", "main_skill_message": "실험 설계",
                      "assignment_statement": "실험 결과를 검증합니다."})
    f.approve_strategy(w.id)
    qs = [f.add_question(w.id, text, 1000) for text in ("직무 역량", "협업", "도전")]
    db.commit()
    result = client, w.id, e.id, qs, f"/api/v4/applications/{w.id}/portfolio"
    generator.close()
    return result


def product_rows():
    generator = app.dependency_overrides[database]()
    db = next(generator)
    result = tuple(tuple(db.scalars(select(model.id).order_by(model.id))) for model in (Artifact, Source, PromptRun))
    generator.close()
    return result


def create_proposal(client, path):
    state = client.get(path).json()
    response = client.post(path + "/propose", headers={"Idempotency-Key": "proposal-http-1"},
                           json={"expected_revision": state["input_revision"], "use_ai": False})
    assert response.status_code == 200, response.text
    return client.get(path).json()


def body_for(state, evidence_id):
    return {"expected_revision": state["decision_revision"], "proposal_id": state["proposal"]["id"],
            "proposal_version": state["proposal"]["version"], "disposition": "DIRECT", "persona_text": "검증하는 연구원",
            "items": [{"question_id": q["id"], "identity_role": f"역할{i}", "primary_message": f"메시지{i}",
                       "evidence_ids": [evidence_id], "evidence_role": f"수행{i}", "climax": f"장면{i}"}
                      for i, q in enumerate(state["questions"])]}


def test_http_get_no_mutation_decide_retry_separate_approvals_and_conflict(http_joint):
    c, wid, eid, _, path = http_joint
    before = product_rows()
    assert c.get(path).status_code == 200
    assert c.get(path).json() == c.get(path).json()
    assert before == product_rows()
    state = create_proposal(c, path)
    payload = body_for(state, eid)
    first = c.post(path + "/decide", json=payload, headers={"Idempotency-Key": "decision-http-1"})
    assert first.status_code == 200, first.text
    assert c.post(path + "/decide", json=payload, headers={"Idempotency-Key": "decision-http-1"}).json()["id"] == first.json()["id"]
    before = product_rows()
    assert c.post(path + "/decide", json=payload, headers={"Idempotency-Key": "competing-http-2"}).status_code == 409
    assert before == product_rows()
    assert c.post(f"/api/applications/{wid}/actions/approve-portfolio", json={}).status_code == 409
    assert c.post(f"/api/applications/{wid}/actions/approve-strategy", json={}).status_code == 200
    assert c.post(f"/api/applications/{wid}/actions/approve-portfolio", json={}).status_code == 200
    current = c.get(path).json()
    assert current["persona"]["status"] == "LOCKED" and current["portfolio"]["status"] == "LOCKED"


@pytest.mark.parametrize("change", [{"proposal_version": 99}, {"expected_revision": "0" * 64},
                                   {"proposal_id": "somebody-else"}, {"persona_candidate_ids": ["forged"]}])
def test_forged_and_stale_decisions_are_409_without_partial_product_rows(http_joint, change):
    c, _, eid, _, path = http_joint
    state = create_proposal(c, path)
    before = product_rows()
    response = c.post(path + "/decide", headers={"Idempotency-Key": "invalid-decision"}, json={**body_for(state, eid), **change})
    assert response.status_code == 409, response.text
    assert product_rows() == before


def test_auth_scope_flag_schema_injection_and_disabled_flag_cannot_bypass_saved_hold(http_joint, monkeypatch):
    c, wid, eid, _, path = http_joint
    state = create_proposal(c, path)
    for injected in ({"owner_id": "private-marker"}, {"approved": True}, {"guide": {"text": "private-marker"}}):
        response = c.post(path + "/decide", headers={"Idempotency-Key": "inject-http-1"}, json={**body_for(state, eid), **injected})
        assert response.status_code == 422 and "private-marker" not in response.text
    c.headers["Authorization"] = "Bearer bob-key"
    assert c.get(path).status_code == 404
    assert c.post(path + "/decide", json=body_for(state, eid), headers={"Idempotency-Key": "cross-owner-1"}).status_code == 404
    c.headers.pop("Authorization")
    assert c.get(path).status_code == 401
    c.headers["Authorization"] = "Bearer alice-key"
    payload = {"expected_revision": state["decision_revision"], "proposal_id": state["proposal"]["id"],
               "proposal_version": state["proposal"]["version"], "disposition": "HOLD", "reason": "원자료 확인"}
    assert c.post(path + "/decide", json=payload, headers={"Idempotency-Key": "hold-http-1"}).status_code == 200
    monkeypatch.setenv("CAREER_JOINT_PORTFOLIO_ENABLED", "0")
    assert c.get(path).status_code == 404
    assert c.post(f"/api/applications/{wid}/actions/approve-portfolio", json={}).status_code == 409


def test_ai_proposal_uses_existing_budget_guard_before_any_model_or_product_write(http_joint, monkeypatch):
    c, _, _, _, path = http_joint
    state = c.get(path).json()
    calls = []
    @contextmanager
    def deny(*args):
        calls.append(args[-1])
        raise BudgetExceeded("합성 한도 초과")
        yield
    monkeypatch.setattr("career.activity.provider_available", lambda: True)
    monkeypatch.setattr("career.usage_limits.request_budget_scope", deny)
    monkeypatch.setattr(Workflow, "ai", lambda *a, **k: pytest.fail("over quota model call"))
    before = product_rows()
    without_confirmation = c.post(path + "/propose", json={"expected_revision": state["input_revision"], "use_ai": True},
                                  headers={"Idempotency-Key": "missing-transfer-confirmation"})
    assert without_confirmation.status_code == 422 and calls == []
    response = c.post(path + "/propose", json={"expected_revision": state["input_revision"], "use_ai": True, "external_transfer_confirmed": True},
                      headers={"Idempotency-Key": "ai-over-quota"})
    assert response.status_code == 503 and calls == ["portfolio-propose"]
    assert product_rows() == before
