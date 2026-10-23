# ruff: noqa: F811 -- shared HTTP fixture
from copy import deepcopy

from career.api import app, database
from career.models import Artifact, Workspace
from sqlalchemy import select
from test_api import client  # noqa: F401


def target(client):
    client.headers["Authorization"] = "Bearer alice-key"
    workspace = client.post("/api/applications", json={"company": "합성회사", "role": "분석가",
                                                      "jd_raw": "분석 보고서 작성"}).json()
    evidence = client.post("/api/evidence", json={"title": "합성 경험", "body": "직접 실험을 설계했습니다.",
        "source_title": "synthetic", "ownership": "USER", "confirmed": True}).json()
    return workspace["id"], evidence["id"]


def test_http_experience_registration_and_review_without_job_keep_unverified_status(client, monkeypatch):
    client.headers["Authorization"] = "Bearer alice-key"
    monkeypatch.setenv("CAREER_CONTEXT_PREVIEW_ENABLED", "1")
    evidence = client.post("/api/evidence", json={"title": "처음 입력한 경험", "body": "검증 전 경험 정리",
        "source_title": "synthetic", "confirmed": False}).json()
    assert evidence["status"] == "UNVERIFIED"
    reviewed = client.post("/api/v4/context/preview", json={"task_type": "EXPERIENCE_REVIEW",
                           "required_evidence_ids": [evidence["id"]]})
    assert reviewed.status_code == 200
    assert reviewed.json()["payload"]["experiences"][0]["status"] == "UNVERIFIED"
    assert client.get("/api/applications").json() == []
    stored = next(row for row in client.get("/api/evidence").json() if row["id"] == evidence["id"])
    assert stored["status"] == "UNVERIFIED"


def test_i02_is_off_by_default_and_enabled_routes_remain_authenticated_read_only(client, monkeypatch):
    workspace, evidence = target(client)
    card, plan = f"/api/v4/experience-cards/{evidence}", f"/api/v4/applications/{workspace}/plan-preview"
    monkeypatch.delenv("CAREER_CONTEXT_PREVIEW_ENABLED", raising=False)
    body = {"task_type": "EXPERIENCE_REVIEW", "required_evidence_ids": [evidence]}
    assert client.get(card).status_code == client.get(plan).status_code == 404
    assert client.post("/api/v4/context/preview", json=body).status_code == 404
    monkeypatch.setenv("CAREER_CONTEXT_PREVIEW_ENABLED", "1")
    before = client.get(f"/api/applications/{workspace}").json()
    first = client.post("/api/v4/context/preview", json=body)
    assert first.status_code == 200, first.text
    assert first.json()["manifest"]["owner_id"] == "alice"
    assert first.json()["status"] == "INPUT_READY_OFFLINE"
    assert not first.json()["can_execute"] and not first.json()["manifest"]["external_transfer_allowed"]
    assert client.post("/api/v4/context/preview", json=body).json() == first.json()
    assert client.get(card).json()["mode"] == "READ_ONLY_PROJECTION"
    assert client.get(plan).json()["mode"] == "SHADOW_ONLY"
    assert client.post(plan, json={"approve": True}).status_code == 405
    resume = client.get(plan, params={"intent": "RESUME_ONLY"}).json()
    assert any(n["kind"] == "RESUME_COMPOSITION" for n in resume["nodes"])
    assert not any(n["kind"] == "CLAIM_PLAN" for n in resume["nodes"])
    assert client.get(f"/api/applications/{workspace}").json() == before
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get(card).status_code == client.get(plan).status_code == 404
    assert client.post("/api/v4/context/preview", json=body).status_code == 404
    client.headers.clear()
    assert client.get(card).status_code == client.get(plan).status_code == 401
    assert client.post("/api/v4/context/preview", json=body).status_code == 401


def test_http_context_scope_revision_and_authority_injection_fail_without_content_echo(client, monkeypatch):
    workspace, evidence = target(client)
    monkeypatch.setenv("CAREER_CONTEXT_PREVIEW_ENABLED", "1")
    endpoint = "/api/v4/context/preview"
    body = {"task_type": "JOB_ASSESS", "application_id": workspace}
    result = client.post(endpoint, json=body).json()
    assert result["payload"]["experiences"] == []
    for injection in ({"user_id": "private-marker"}, {"approved": True}, {"external_transfer_consent": True},
                      {"vector": ["private-marker"]}, {"task_type": "private-marker"}):
        response = client.post(endpoint, json={**body, **injection})
        assert response.status_code == 422 and "private-marker" not in response.text
    key = "APPLICATION:" + workspace
    stale = client.post(endpoint, json={**body, "expected_revisions": {key: "0" * 64}})
    assert stale.status_code == 409
    assert client.post(endpoint, json={**body, "question_id": "foreign"}).status_code == 422
    assert client.post(endpoint, json={**body, "task_type": "COVER_WRITE", "question_id": "foreign"}).status_code == 404
    held = client.post(endpoint, json={**body, "max_input_tokens": 1}).json()
    assert held["status"] == "HOLD" and held["payload"] is None
    assert not held["completion_proof"]


def test_http_required_skipped_and_frozen_material_are_never_auto_approved(client, monkeypatch):
    workspace, evidence = target(client)
    monkeypatch.setenv("CAREER_CONTEXT_PREVIEW_ENABLED", "1")
    generator = app.dependency_overrides[database]()
    db = next(generator)
    ws = db.scalar(select(Workspace).where(Workspace.id == workspace))
    skipped = Artifact(user_id="alice", workspace_id=workspace, kind="OpportunityAssessment", status="SKIPPED",
                       version=1, data={"eligibility": []})
    db.add(skipped)
    db.commit()
    plan = client.get(f"/api/v4/applications/{workspace}/plan-preview").json()
    assert next(n for n in plan["nodes"] if n["kind"] == "ELIGIBILITY")["status"] == "BLOCKED"
    assert next(n for n in plan["nodes"] if n["kind"] == "STRATEGY")["status"] == "PLANNED"
    ws.state = "SUBMISSION_FROZEN"
    frozen = Artifact(user_id="alice", workspace_id=workspace, kind="SubmissionBundle", status="LOCKED",
                      version=1, data={"documents": ["unchanged synthetic snapshot"]})
    db.add(frozen)
    db.commit()
    original = deepcopy(frozen.data)
    plan = client.get(f"/api/v4/applications/{workspace}/plan-preview").json()
    assert next(n for n in plan["nodes"] if n["kind"] == "SUBMISSION_CONFIRMATION")["status"] == "WAITING_APPROVAL"
    db.refresh(frozen)
    db.refresh(ws)
    assert frozen.data == original and ws.state == "SUBMISSION_FROZEN"
    db.close()
    generator.close()
