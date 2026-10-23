# ruff: noqa: F811 -- shared fixtures
import json
from copy import deepcopy

import pytest
from career.api import app, database
from career.guide_publication import publication_projection, publishable_guide
from career.models import Artifact, PromptRun
from career.providers import FakeLLMProvider
from career.truth import view
from career.writing_plans import catalog, context, digest, guide_for, persist, public_preview, require_current
from test_api import client  # noqa: F401
from test_workflow import (
    doc,
    flow,  # noqa: F401
    verify_claim,
)


def archived():
    meta = catalog()[0]["selection_metadata"]
    return meta, guide_for(meta["source_company"], meta["source_role_name"],
                           {"text": meta["original_prompt"], "limit": 600})


def assert_hidden(value, original):
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    for paragraph in original["reference_example"]["paragraphs"]:
        assert paragraph["text"] not in serialized
    assert original["source"]["source_quote"] not in serialized


def test_projection_preserves_original_and_structure_but_never_trusts_imported_rights():
    _, original = archived()
    before = deepcopy(original)
    display = publishable_guide({**original, "rights_status": "PUBLIC_APPROVED"})
    assert_hidden(display, original)
    assert original == before
    assert display["allocation"] == original["allocation"]
    assert display["source"]["source_url"] == original["source"]["source_url"]
    assert display["reference_example"]["paragraphs"] == []
    assert display["rights_status"] == "RIGHTS_PENDING"
    assert publication_projection(display) == display


def test_current_screen_plan_and_writer_share_publishable_snapshot(flow):
    service, workspace, _ = flow
    meta, original = archived()
    workspace.company, workspace.role = meta["source_company"], meta["source_role_name"]
    q = service.add_question(workspace.id, meta["original_prompt"], 600)
    plan = persist(service, workspace.id, q["id"])
    screen = public_preview(service, workspace.id, q["id"])
    writer = context(plan)
    assert screen["guide"] == writer["guide"] == plan.data["guide"]
    assert digest(screen["guide"]) == screen["guide_snapshot_sha256"] == writer["guide_snapshot_sha256"]
    assert_hidden(screen, original)
    assert_hidden(writer, original)
    assert screen["guide"]["origin"] == "ARCHIVED_REFERENCE"
    assert [part["approximate_characters"] for part in screen["guide"]["allocation"]] == [70, 120, 280, 130]


def test_exact_guide_passes_existing_claim_approval_and_writer_without_reference_text(flow):
    service, workspace, evidence = flow
    meta, original = archived()
    workspace.company, workspace.role = meta["source_company"], meta["source_role_name"]
    service.approve_strategy(workspace.id)
    q = service.add_question(workspace.id, meta["original_prompt"], 600)
    recorded = {}

    class Capture(FakeLLMProvider):
        def structured(self, stage, values, schema):
            recorded[stage] = deepcopy(values)
            return super().structured(stage, values, schema)

    service.provider = Capture({"question_brief": {
        "question_id": q["id"], "question_type": "JOB_COMPETENCY", "evaluation_intent": "근거 검증",
        "primary_message": "평가를 검증했습니다.", "evidence_ids": [evidence.id]}, "writer": doc(evidence)})
    service.question_brief(workspace.id, q["id"])
    verify_claim(service, workspace, q["id"])
    service.approve_question(workspace.id, q["id"])
    service.draft(workspace.id, q["id"])
    screen = public_preview(service, workspace.id, q["id"])
    assert recorded["question_brief"]["writing_plan"] == recorded["writer"]["writing_plan"]
    assert recorded["writer"]["writing_plan"]["guide"] == screen["guide"]
    assert_hidden(recorded, original)


def test_old_plan_requires_reconfirmation_and_historical_bundle_is_not_rewritten(flow):
    service, workspace, _ = flow
    meta, original = archived()
    workspace.company, workspace.role = meta["source_company"], meta["source_role_name"]
    q = service.add_question(workspace.id, meta["original_prompt"], 600)
    plan = persist(service, workspace.id, q["id"])
    plan.data = {**plan.data, "guide": original, "guide_snapshot_sha256": digest(original),
                 "input_revision": "old-before-publication-policy"}
    old_data = deepcopy(plan.data)
    assert not public_preview(service, workspace.id, q["id"])["plan_current"]
    brief = Artifact(data={"writing_plan_id": plan.id})
    with pytest.raises(ValueError, match="바뀌었"):
        require_current(service, workspace.id, q["id"], brief)
    bundle = Artifact(user_id=service.user, workspace_id=workspace.id, kind="SubmissionBundle",
                      status="LOCKED", data={"documents": [{"writing_plan": old_data}]})
    before = deepcopy(bundle.data)
    assert_hidden(view(bundle), original)
    assert bundle.data == before and bundle.status == "LOCKED" and plan.data == old_data


def test_http_preview_save_history_trace_export_hide_examples_without_database_mutation(client):
    client.headers["Authorization"] = "Bearer alice-key"
    meta, original = archived()
    ws = client.post("/api/applications", json={"company": meta["source_company"],
                     "role": meta["source_role_name"], "jd_raw": "합성 개발 공고"}).json()
    q = client.post(f"/api/applications/{ws['id']}/actions/add-question",
                    json={"text": meta["original_prompt"], "limit": 600}).json()
    path = f"/api/applications/{ws['id']}/questions/{q['id']}/writing-plan"
    screen = client.get(path).json()
    saved = client.post(path, json={"expected_revision": screen["state_revision"]})
    assert saved.status_code == 200
    assert_hidden(saved.json(), original)
    generator = app.dependency_overrides[database]()
    db = next(generator)
    legacy = Artifact(user_id="alice", workspace_id=ws["id"], kind="SubmissionBundle", status="LOCKED",
                      data={"documents": [{"guide": original}]})
    trace = PromptRun(user_id="alice", stage="writer", provider="synthetic",
                      data={"input": {"writing_plan": {"guide": original}}})
    db.add_all([legacy, trace])
    db.commit()
    before = deepcopy(legacy.data)
    for route in (path, f"/api/applications/{ws['id']}", "/api/export", f"/api/traces/{trace.id}"):
        response = client.get(route)
        assert response.status_code == 200
        assert_hidden(response.json(), original)
    assert_hidden(view(trace), original)
    db.refresh(legacy)
    assert legacy.data == before and legacy.status == "LOCKED"
    db.close()
    generator.close()
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get(path).status_code == 404
