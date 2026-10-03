from test_api import client  # noqa: F401


def test_mutation_idempotency(client):  # noqa: F811
    client.headers["Authorization"] = "Bearer alice-key"
    w = client.post("/api/applications", json={"company": "demo", "role": "demo", "jd_raw": "demo"}).json()
    path = f"/api/applications/{w['id']}/actions/add-question"
    headers = {"Idempotency-Key": "request-1"}
    body = {"text": "질문", "limit": 1000}
    first = client.post(path, json=body, headers=headers)
    second = client.post(path, json=body, headers=headers)
    assert first.json() == second.json()
    assert len(client.get("/api/applications/" + w["id"]).json()["data"]["questions"]) == 1
    assert client.post(path, json={"text": "다른 질문"}, headers=headers).status_code == 409


def test_stable_alias_preserves_retry_key_and_conflict(client):  # noqa: F811
    client.headers["Authorization"] = "Bearer alice-key"
    w = client.post("/api/applications", json={"company": "demo", "role": "analyst", "jd_raw": "report"}).json()
    path = f"/api/opportunities/{w['id']}/analyze"
    body = {"manual": {"base_profession": "analyst", "actual_outputs": ["report"]}}
    headers = {"Idempotency-Key": "stable-alias-retry"}
    first = client.post(path, json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert client.post(path, json=body, headers=headers).json() == first.json()
    body["manual"]["actual_outputs"] = ["changed output"]
    assert client.post(path, json=body, headers=headers).status_code == 409
    artifacts = client.get(f"/api/applications/{w['id']}").json()["artifacts"]
    assert len([a for a in artifacts if a["kind"] == "OpportunityBrief"]) == 1
