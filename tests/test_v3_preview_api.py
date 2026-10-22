# ruff: noqa: F811 -- shared HTTP fixture
from test_api import client  # noqa: F401


def target(client):
    client.headers["Authorization"] = "Bearer alice-key"
    workspace = client.post("/api/applications", json={
        "company": "합성회사", "role": "분석가", "jd_raw": "분석 보고서 작성",
    }).json()
    evidence = client.post("/api/evidence", json={
        "title": "합성 경험", "body": "실험을 직접 설계했습니다.", "source_title": "synthetic-results",
        "ownership": "USER", "confirmed": True,
    }).json()
    return workspace["id"], evidence["id"]


def test_disabled_by_default_and_preview_cannot_execute(client, monkeypatch):
    workspace, evidence = target(client)
    paths = [f"/api/v3/applications/{workspace}/plan-preview", f"/api/v3/experience-cards/{evidence}"]
    monkeypatch.delenv("CAREER_V3_PREVIEW_ENABLED", raising=False)
    assert all(client.get(path).status_code == 404 for path in paths)
    monkeypatch.setenv("CAREER_V3_PREVIEW_ENABLED", "1")
    first = client.get(paths[0])
    assert first.status_code == 200, first.text
    assert first.json()["mode"] == "SHADOW_ONLY"
    assert first.json()["can_execute"] is False and first.json()["completion_proof"] is False
    assert client.get(paths[0]).json() == first.json()
    assert client.get(paths[1]).json()["mode"] == "READ_ONLY_PROJECTION"
    assert client.post(paths[0], json={"approve": True, "submitted": True}).status_code == 405
    assert client.get(paths[0], params={"intent": "SUBMIT"}).status_code == 422
    assert client.get(f"/api/applications/{workspace}").json()["state"] == "CREATED"


def test_preview_authentication_owner_isolation_and_resume_only(client, monkeypatch):
    workspace, evidence = target(client)
    monkeypatch.setenv("CAREER_V3_PREVIEW_ENABLED", "1")
    paths = [f"/api/v3/applications/{workspace}/plan-preview", f"/api/v3/experience-cards/{evidence}"]
    resume = client.get(paths[0], params={"intent": "RESUME_ONLY"}).json()
    assert any(n["kind"] == "RESUME_COMPOSITION" for n in resume["nodes"])
    assert not any(n["kind"] == "CLAIM_PLAN" for n in resume["nodes"])
    client.headers["Authorization"] = "Bearer bob-key"
    assert all(client.get(path).status_code == 404 for path in paths)
    client.headers.clear()
    assert all(client.get(path).status_code == 401 for path in paths)
