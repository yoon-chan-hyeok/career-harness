# ruff: noqa: F811 -- reused isolated authenticated fixtures
import pytest
from career.api import app, database
from career.artifacts import save
from career.models import Artifact, Evidence, PromptRun, Source
from career.rule_pilot import snapshot
from career.workflow import Workflow
from sqlalchemy import select
from test_api import client  # noqa: F401
from test_joint_portfolio_api import http_joint  # noqa: F401
from test_rule_pilot import pilot  # noqa: F401
from test_workflow import flow  # noqa: F401


@pytest.fixture
def rule_http(http_joint, pilot, monkeypatch):
    c, wid, eid, qs, _ = http_joint
    monkeypatch.setenv("CAREER_RULE_PILOT_USER_ID", "alice")
    generator = app.dependency_overrides[database]()
    db = next(generator)
    e = db.get(Evidence, eid)
    assert e is not None
    document, _ = save(db, "alice", wid, "Draft", {"text": e.body, "selected_evidence_ids": [eid],
        "claims": [{"text": e.body, "type": "FACT", "evidence_ids": [eid], "metric_ids": [],
                    "profile_fact_ids": [], "company_source_ids": [], "support": "SUPPORTED", "ownership_ok": True}]},
        sources=[e.source_id], slot=qs[0]["id"])
    db.commit()
    result = c, wid, document.id, f"/api/v4/applications/{wid}/rules"
    generator.close()
    return result


def product_rows():
    generator = app.dependency_overrides[database]()
    db = next(generator)
    result = tuple(tuple(db.scalars(select(model.id).order_by(model.id))) for model in (Artifact, Source, PromptRun))
    generator.close()
    return result


def body(c, path):
    state = c.get(path).json()
    return {"expected_revision": state["revision"], "rule_id": "SYNTHETIC-RULE-1", "rule_version": 1, "confirmed": True}


def test_http_review_eval_approval_are_separate_and_read_only_get_then_actual_document_check(rule_http):
    c, wid, document_id, path = rule_http
    before = product_rows()
    assert c.get(path).json() == c.get(path).json()
    assert before == product_rows()
    assert c.post(path + "/activate", json=body(c, path), headers={"Idempotency-Key": "no-evaluation"}).status_code == 409
    for action in ("source-review", "evaluate", "activate"):
        response = c.post(path + "/" + action, json=body(c, path), headers={"Idempotency-Key": "rule-" + action})
        assert response.status_code == 200, response.text
    doc_path = f"/api/v4/applications/{wid}/rule-documents"
    state = c.get(doc_path + "/" + document_id).json()
    request = {"expected_revision": state["revision"], "document_id": document_id, "document_version": state["version"]}
    response = c.post(doc_path + "/check", json=request, headers={"Idempotency-Key": "check-document-1"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["records"][0]["verdict"] == "SELECTED_NOT_TRIGGERED"
    before = product_rows()
    replay = c.post(doc_path + "/check", json=request, headers={"Idempotency-Key": "check-document-1"})
    assert replay.json()["id"] == response.json()["id"] and product_rows() == before


def test_scope_feature_flag_schema_and_stale_revision_do_not_write_partial_rule_results(rule_http, monkeypatch):
    c, _, _, path = rule_http
    original = body(c, path)
    for injection in ({"status": "PASSED"}, {"approved": True}, {"owner_id": "private-marker"}, {"source_file": "private-marker"}):
        response = c.post(path + "/source-review", json={**original, **injection}, headers={"Idempotency-Key": "rule-inject"})
        assert response.status_code == 422 and "private-marker" not in response.text
    first = c.post(path + "/source-review", json=original, headers={"Idempotency-Key": "source-review-real"})
    assert first.status_code == 200
    before = product_rows()
    assert c.post(path + "/source-review", json=original, headers={"Idempotency-Key": "source-review-old"}).status_code == 409
    assert before == product_rows()
    c.headers["Authorization"] = "Bearer bob-key"
    assert c.get(path).status_code == 404
    c.headers.pop("Authorization")
    assert c.get(path).status_code == 401
    c.headers["Authorization"] = "Bearer alice-key"
    monkeypatch.setenv("CAREER_RULE_PILOT_ENABLED", "0")
    assert c.get(path).status_code == 404


def test_wrong_application_document_is_denied_without_cross_scope_trace(rule_http):
    c, wid, document_id, _ = rule_http
    other = c.post("/api/applications", json={"company": "별도회사", "role": "연구원", "jd_raw": "평가"}).json()["id"]
    before = product_rows()
    assert c.get(f"/api/v4/applications/{other}/rule-documents/{document_id}").status_code == 404
    response = c.post(f"/api/v4/applications/{other}/rule-documents/check", json={
        "expected_revision": "0" * 64, "document_id": document_id, "document_version": 1}, headers={"Idempotency-Key": "cross-app-check"})
    assert response.status_code == 404 and product_rows() == before
    generator = app.dependency_overrides[database]()
    db = next(generator)
    assert snapshot(Workflow(db, "alice"), other)["rules"][0]["states"]["RuleActivation"] is None
    assert wid != other
    generator.close()
