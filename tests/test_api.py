import json

import pytest
from career.api import app, database
from career.db import Base
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def sessions():
        with Session(engine, expire_on_commit=False) as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[database] = sessions
    monkeypatch.setenv("AUTH_TOKENS", json.dumps({"alice-key": "alice", "bob-key": "bob"}))
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


def test_auth_and_cross_user(client):
    assert client.get("/api/applications").status_code == 401
    a = {"Authorization": "Bearer alice-key"}
    b = {"Authorization": "Bearer bob-key"}
    w = client.post(
        "/api/applications", headers=a, json={"company": "Demo", "role": "Analyst", "jd_raw": "Report"}
    ).json()
    assert client.get("/api/applications/" + w["id"], headers=b).status_code == 404
    assert client.get("/api/applications", headers=b).json() == []
    assert client.delete("/api/applications/" + w["id"], headers=b).status_code == 404


def test_conversation_http_isolation_and_retries(client):
    client.headers["Authorization"] = "Bearer alice-key"
    w = client.post(
        "/api/applications", json={"company": "Demo", "role": "Analyst", "jd_raw": "Report"}
    ).json()
    path = f"/api/applications/{w['id']}/conversation"
    body = {"text": "문항 추가: 문제 해결 경험", "client_id": "test-message-123"}
    first = client.post(path, json=body)
    assert first.status_code == 200
    assert client.post(path, json=body).json()["id"] == first.json()["id"]
    assert len(client.get(path).json()) == 1
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get(path).status_code == 404
    assert client.post(path, json=body).status_code == 404


def test_reviewer_labels_are_persisted_scoped_and_idempotent(client):
    from career.models import Artifact

    client.headers["Authorization"] = "Bearer alice-key"
    w = client.post(
        "/api/applications", json={"company": "Demo", "role": "Analyst", "jd_raw": "Report"}
    ).json()
    generator = app.dependency_overrides[database]()
    db = next(generator)
    artifact = Artifact(
        user_id="alice",
        workspace_id=w["id"],
        kind="Review",
        data={"issues": [{"code": "TEST", "priority": "P2", "message": "질문 답을 앞에"}]},
    )
    db.add(artifact)
    db.flush()
    ident = artifact.id
    db.commit()
    generator.close()
    path = f"/api/artifacts/{ident}/review-labels"
    first = client.post(path, json={"issue_index": 0, "valid": True})
    assert first.status_code == 200
    assert client.post(path, json={"issue_index": 0, "valid": False}).json()["id"] == first.json()["id"]
    assert client.get("/api/telemetry").json()["reviewer_metrics"]["issue_precision"] == 0
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.post(path, json={"issue_index": 0, "valid": True}).status_code == 404


def test_http_e2e_manual_workflow(client):
    client.headers["Authorization"] = "Bearer alice-key"
    e = client.post(
        "/api/evidence",
        json={
            "title": "Analysis",
            "body": "실험을 설계했습니다.",
            "source_title": "experiment",
            "ownership": "USER",
            "confirmed": True,
        },
    ).json()
    w = client.post(
        "/api/applications", json={"company": "Demo", "role": "Analyst", "jd_raw": "Report"}
    ).json()

    def act(action, body):
        response = client.post(f"/api/applications/{w['id']}/actions/{action}", json=body)
        assert response.status_code == 200, response.text
        return response.json()

    act("analyze", {"manual": {"actual_outputs": ["Report"], "base_profession": "Analyst"}})
    act(
        "evidence-map",
        {
            "manual": {
                "items": [
                    {
                        "evidence_id": e["id"],
                        "job_output_id": "Report",
                        "classification": "DIRECT",
                        "evidence_strength": "STRONG",
                        "ownership_strength": "STRONG",
                        "rationale": "experiment",
                    }
                ],
                "uncovered_outputs": [],
            }
        },
    )
    act(
        "strategy",
        {
            "manual": {
                "positioning": "Analyst",
                "base_profession_identity": "Analyst",
                "main_skill_message": "분석",
                "assignment_statement": "실험 설계",
            }
        },
    )
    act("approve-strategy", {})
    q = act("add-question", {"text": "직무 역량", "limit": 1000})
    brief = act(
        "question-brief",
        {
            "qid": q["id"],
            "manual": {
                "question_id": q["id"],
                "question_type": "JOB_COMPETENCY",
                "evaluation_intent": "검증",
                "primary_message": "실험 설계",
                "evidence_ids": [e["id"]],
            },
        },
    )
    from types import SimpleNamespace

    from test_workflow import proof_payload

    act("claim-test", {"qid": q["id"], "artifact_id": brief["id"], "confirmed": True,
                       "manual": proof_payload(brief["data"], SimpleNamespace(**e))})
    act("approve-question", {"qid": q["id"]})
    document = {
        "text": e["body"],
        "claims": [
            {
                "text": e["body"],
                "type": "FACT",
                "evidence_ids": [e["id"]],
                "support": "SUPPORTED",
                "ownership_ok": True,
            }
        ],
    }
    act("generate", {"qid": q["id"], "manual": document})
    act("review", {"qid": q["id"], "manual_verified": True})
    act("final-lock", {"qid": q["id"]})
    final_context = client.get(f"/api/applications/{w['id']}/final-review-context").json()
    act("final-review", {"context_hash": final_context["context_hash"], "role_noun": "Analyst",
        "role_alignment": "MATCH", "assignment_answer": "직접 실험을 설계하고 분석 결과 보고서를 작성할 수 있습니다.",
        "motivation_answer": "실험과 분석을 통해 문제를 확인하는 분석가의 본업을 배우고 싶습니다.",
        "wants_core_work": True, "evidence_answer": "직접 실험을 설계한 경험을 분석 업무의 근거로 연결했습니다.",
        "citations": [{"evidence_id": e["id"], "quote": e["body"]}],
        "gaps_answer": "실무 분석 업무 경험은 아직 부족합니다.", "decision": "PASS", "return_stage": "NONE", "confirmed": True})
    act("ready", {})
    bundle = act("freeze", {})
    assert bundle["data"]["submitted_at"] is None
    act("interview-handoff", {})
    act("confirm", {"confirmed": True})
    assert client.get(f"/api/applications/{w['id']}/submission").json()["submitted_at"]
    act("outcome", {"result": "CODING_FAIL"})
    assert not act("postmortem", {})["data"]["writing_rule_updated"]
    deleted = client.delete("/api/sources/" + e["source_id"])
    assert deleted.status_code == 200
    assert client.get("/api/evidence/search?q=실험").json() == []
    assert client.get(f"/api/applications/{w['id']}/submission").json()["bundle"]["data"] == bundle["data"]
    assert client.delete("/api/applications/" + w["id"]).status_code == 200
    assert client.get("/api/applications").json() == []
