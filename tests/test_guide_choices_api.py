# ruff: noqa: F811 -- shared HTTP fixture
import json

import pytest
from career.api import app, database
from career.models import Artifact, PromptRun, Source
from career.question_guide_import import import_file, load_catalog
from sqlalchemy import select
from test_api import client  # noqa: F401
from test_question_guide_retrieval import policy, release, source


@pytest.fixture
def api_choice(client, monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_GUIDE_SELECTION_ENABLED", "1")
    catalog, ledger, input_path = tmp_path / "guides", tmp_path / "reviews.json", tmp_path / "input.json"
    input_path.write_text(json.dumps(source()), encoding="utf-8")
    import_file(input_path, catalog)
    ledger.write_text(json.dumps({"reviews": [release(load_catalog(catalog)[0]).model_dump(mode="json")]}), encoding="utf-8")
    monkeypatch.setenv("CAREER_GUIDE_CATALOG_DIR", str(catalog))
    monkeypatch.setenv("CAREER_GUIDE_RELEASES_PATH", str(ledger))
    client.headers["Authorization"] = "Bearer alice-key"
    w = client.post("/api/applications", json={"company": "합성회사", "role": "개발", "jd_raw": "검증 보고서"}).json()
    q = client.post(f"/api/applications/{w['id']}/actions/add-question",
                   json={"text": source()["question"], "limit": 600}).json()
    return client, w, q, f"/v4/applications/{w['id']}/questions/{q['id']}", ledger


def count_product_rows():
    generator = app.dependency_overrides[database]()
    db = next(generator)
    result = tuple(tuple(db.scalars(select(model.id).order_by(model.id))) for model in (Artifact, Source, PromptRun))
    db.close()
    generator.close()
    return result


def confirm(client, path):
    state = client.get("/api" + path + "/guides").json()
    response = client.post("/api" + path + "/contract", headers={"Idempotency-Key": "contract-confirm-1"},
                           json={"expected_revision": state["contract_state_revision"], "length": policy(), "confirmed": True})
    assert response.status_code == 200, response.text


def request_body(state, **changes):
    candidate = state["retrieval"]["candidates"][0]
    return {"expected_revision": state["selection_revision"], "request_key": state["retrieval"]["request_key"],
        "guide_id": candidate["guide_id"], "guide_version": candidate["guide_version"],
        "guide_snapshot_hash": candidate["guide_snapshot_hash"], **changes}


def test_real_curator_files_get_post_retry_and_existing_plan_snapshot(api_choice):
    client, w, q, path, _ = api_choice
    confirm(client, path)
    before = count_product_rows()
    state = client.get("/api" + path + "/guides").json()
    assert client.get("/api" + path + "/guides").json() == state
    assert before == count_product_rows()
    assert state["retrieval"]["candidates"][0]["match_type"] == "EXACT"
    body = request_body(state, allocation_budgets=[60, 120, 280, 140])
    first = client.post("/api" + path + "/guide-choice", json=body, headers={"Idempotency-Key": "guide-select-1"})
    assert first.status_code == 200, first.text
    assert client.post("/api" + path + "/guide-choice", json=body, headers={"Idempotency-Key": "guide-select-1"}).json()["id"] == first.json()["id"]
    plan = client.get(f"/api/applications/{w['id']}/questions/{q['id']}/writing-plan").json()
    assert plan["guide_choice"]["guide_id"] == body["guide_id"]
    assert plan["guide_choice"]["allocation_budgets"] == [60, 120, 280, 140]
    assert plan["plan_current"] and plan["guide_selection_enabled"]
    assert plan["guide_snapshot_sha256"] == plan["plan"]["data"]["guide_snapshot_sha256"]
    assert first.json()["id"] in plan["plan"]["depends_on"]
    assert not plan["can_design"]  # A guide choice never approves a strategy or personal evidence.
    before = count_product_rows()
    stale_second = client.post("/api" + path + "/guide-choice", json=body,
                               headers={"Idempotency-Key": "competing-select-2"})
    assert stale_second.status_code == 409
    assert before == count_product_rows()


@pytest.mark.parametrize("change", [{"expected_revision": "0" * 64}, {"request_key": "0" * 64},
                                   {"guide_version": 99}, {"allocation_budgets": [600, 600, 600, 600]}])
def test_stale_forged_or_invalid_choices_are_409_without_partial_product_writes(api_choice, change):
    client, _, _, path, _ = api_choice
    confirm(client, path)
    state = client.get("/api" + path + "/guides").json()
    before = count_product_rows()
    response = client.post("/api" + path + "/guide-choice", json=request_body(state, **change),
                           headers={"Idempotency-Key": "invalid-select-1"})
    assert response.status_code == 409, response.text
    assert before == count_product_rows()


def test_flag_owner_scope_auth_and_guide_body_approval_injection(api_choice, monkeypatch):
    client, _, _, path, _ = api_choice
    state = client.get("/api" + path + "/guides").json()
    for injection in ({"guide": {"text": "private-marker"}}, {"approved": True}, {"owner_id": "private-marker"}):
        response = client.post("/api" + path + "/guide-choice", json={**request_body(state), **injection},
                               headers={"Idempotency-Key": "injection-1"})
        assert response.status_code == 422 and "private-marker" not in response.text
    monkeypatch.setenv("CAREER_GUIDE_SELECTION_ENABLED", "0")
    assert client.get("/api" + path + "/guides").status_code == 404
    monkeypatch.setenv("CAREER_GUIDE_SELECTION_ENABLED", "1")
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get("/api" + path + "/guides").status_code == 404
    assert client.post("/api" + path + "/guide-choice", json=request_body(state),
                       headers={"Idempotency-Key": "cross-user-1"}).status_code == 404
    client.headers.clear()
    assert client.get("/api" + path + "/guides").status_code == 401


def test_invalid_curator_file_falls_back_without_leaking_path_or_example(api_choice):
    client, _, _, path, ledger = api_choice
    ledger.write_text('{"private_secret":"catalog-private-marker"}', encoding="utf-8")
    state = client.get("/api" + path + "/guides")
    assert state.status_code == 200
    assert state.json()["catalog_status"] == "UNAVAILABLE"
    assert not state.json()["retrieval"]["candidates"]
    assert "catalog-private-marker" not in state.text and str(ledger) not in state.text
