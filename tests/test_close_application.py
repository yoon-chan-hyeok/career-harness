# ruff: noqa: F811 -- reusable pytest fixtures
from copy import deepcopy

import pytest
from career.api import app, database
from career.db import Record
from career.models import Artifact, Workspace
from sqlalchemy import select
from test_api import client  # noqa: F401 -- pytest fixture
from test_workflow import finish, flow  # noqa: F401 -- pytest fixture


def test_close_requires_confirmed_actual_submission_and_preserves_bundle(flow, db):
    f, w, e = flow
    with pytest.raises(ValueError, match="제출"):
        f.close_application(w.id, True)
    finish(f, w, e)
    from final_review_fixture import confirm_final

    confirm_final(f, w.id)
    f.ready(w.id)
    bundle = f.freeze(w.id)
    before = deepcopy(bundle.data)
    with pytest.raises(ValueError, match="제출"):
        f.close_application(w.id, True)
    f.confirm_submission(w.id, True)
    submitted_at = w.data["submitted_at"]
    with pytest.raises(ValueError, match="확인"):
        f.close_application(w.id, False)
    closed = f.close_application(w.id, True, "전형 결과를 모두 기록함")
    assert closed["state"] == "CLOSED" and closed["closed_at"]
    assert w.data["submitted_at"] == submitted_at and bundle.data == before
    assert bundle.status == "LOCKED"
    assert f.close_application(w.id, True, "전형 결과를 모두 기록함") == closed
    closures = list(db.scalars(select(Record).where(Record.kind == "ApplicationClosure")))
    assert len(closures) == 1 and closures[0].data["bundle_id"] == bundle.id
    with pytest.raises(ValueError, match="보관본"):
        f.add_question(w.id, "추가 문항", 1000)
    # Closed tracking keeps historical reading, interview preparation and outcome notes available.
    assert f.handoff(w.id).depends_on == [bundle.id]
    assert f.outcome(w.id, "FINAL_OFFER").data["result"] == "FINAL_OFFER"


def test_close_http_is_owner_scoped_and_idempotency_protects_reason(client):
    generator = app.dependency_overrides[database]()
    db = next(generator)
    workspace = Workspace(
        user_id="alice",
        company="Demo",
        role="Analyst",
        jd_raw="Report",
        state="SUBMITTED",
        data={"questions": [], "submitted_at": "2026-10-02T00:00:00+00:00"},
    )
    db.add(workspace)
    db.flush()
    bundle = Artifact(
        user_id="alice",
        workspace_id=workspace.id,
        kind="SubmissionBundle",
        status="LOCKED",
        data={"immutable": "exact submitted content"},
        depends_on=[],
        source_ids=[],
        version=1,
        slot="",
    )
    db.add(bundle)
    db.flush()
    workspace.data = {**workspace.data, "submission_bundle_id": bundle.id}
    ident = workspace.id
    db.commit()
    generator.close()
    path = f"/api/applications/{ident}/close"
    assert (
        client.post(path, headers={"Authorization": "Bearer bob-key"}, json={"confirmed": True}).status_code
        == 404
    )
    client.headers.update({"Authorization": "Bearer alice-key", "Idempotency-Key": "close-request-001"})
    denied = client.post(path, json={"confirmed": False})
    assert denied.status_code == 409
    body = {"confirmed": True, "reason": "완료 기록"}
    first = client.post(path, json=body)
    assert first.status_code == 200 and first.json()["state"] == "CLOSED"
    assert client.post(path, json=body).json() == first.json()
    assert client.post(path, json={"confirmed": True, "reason": "다른 메모"}).status_code == 409
    details = client.get(f"/api/applications/{ident}").json()
    assert details["data"]["closure_reason"] == "완료 기록"
    assert details["artifacts"][0]["data"] == {"immutable": "exact submitted content"}


def test_closed_state_cannot_be_forged_without_submission_confirmation(flow):
    f, w, _ = flow
    w.state = "SUBMITTED"
    with pytest.raises(ValueError, match="제출"):
        f.close_application(w.id, True)
    assert w.state == "SUBMITTED"
