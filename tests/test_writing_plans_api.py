# ruff: noqa: F811 -- shared HTTP fixture
from test_api import client  # noqa: F401


def target(client):
    client.headers["Authorization"] = "Bearer alice-key"
    w = client.post("/api/applications", json={
        "company": "테스트회사", "role": "SW 개발", "jd_raw": "서비스 개발 및 검증"
    }).json()
    q = client.post(f"/api/applications/{w['id']}/actions/add-question",
                    json={"text": "직무 역량을 설명하세요.", "limit": 600}).json()
    return f"/api/applications/{w['id']}/questions/{q['id']}/writing-plan"


def test_plan_http_read_save_and_owner_isolation(client):
    path = target(client)
    state = client.get(path).json()
    assert state["guide"]["origin"] == "SUGGESTED_STRUCTURE"
    assert state["plan"] is None and state["can_design"] is False
    body = {"expected_revision": state["state_revision"], "emphasis_state": "active",
            "emphasis": "판단 과정을 먼저", "working_notes": "새 사실로 확정되지 않은 메모"}
    first = client.post(path, json=body)
    assert first.status_code == 200
    assert first.json()["kind"] == "WritingPlan"
    assert client.post(path, json=body).json()["id"] == first.json()["id"]
    second = client.get(path).json()
    assert second["plan_current"]
    assert second["emphasis"]["text"] == body["emphasis"]
    assert second["guide_snapshot_sha256"] == first.json()["data"]["guide_snapshot_sha256"]
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get(path).status_code == 404
    assert client.post(path, json=body).status_code == 404
    client.headers.clear()
    assert client.get(path).status_code == 401


def test_plan_http_revision_and_client_guide_injection_rejected(client):
    path = target(client)
    state = client.get(path).json()
    body: dict[str, object] = {"expected_revision": "0" * 64}
    assert client.post(path, json=body).status_code == 409
    body["expected_revision"] = state["state_revision"]
    body["guide"] = {"question_intent": "임의 가이드"}
    assert client.post(path, json=body).status_code in {400, 422}
    assert client.get(path).json()["plan"] is None

