from test_api import client  # noqa: F401


def test_source_and_review_api_are_owned_idempotent_and_allow_free_manual_flow(client):  # noqa: F811
    client.headers["Authorization"] = "Bearer alice-key"
    workspace = client.post("/api/applications", json={"company": "합성회사", "role": "분석가",
        "jd_raw": "분석 보고서를 작성합니다."}).json()
    path = f"/api/applications/{workspace['id']}/actions/"
    body = {"method": "PASTE", "category": "COMPANY", "title": "합성 회사 소개",
            "text": "합성 회사는 기업 고객에게 데이터 분석 서비스를 제공합니다."}
    first = client.post(path + "research-source", json=body, headers={"Idempotency-Key": "first-source"})
    assert first.status_code == 200, first.text
    research = first.json()
    duplicate = client.post(path + "research-source", json=body, headers={"Idempotency-Key": "first-source"})
    assert duplicate.json()["id"] == research["id"]
    manual = {"actual_outputs": ["보고서"], "base_profession": "분석가"}
    assert client.post(path + "analyze", json={"manual": manual}).status_code == 409
    review_body = {"research_id": research["id"], "mode": "INSUFFICIENT",
                  "limitation": "사업은 확인했지만 실제 내부 채용 계획은 미확인입니다.", "confirmed": False}
    assert client.post(path + "research-confirm", json=review_body).status_code == 409
    review_body["confirmed"] = True
    confirmed = client.post(path + "research-confirm", json=review_body)
    assert confirmed.status_code == 200, confirmed.text
    analysis = client.post(path + "analyze", json={"manual": manual})
    assert analysis.status_code == 200 and confirmed.json()["id"] in analysis.json()["depends_on"]
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.post(path + "research-confirm", json=review_body).status_code == 404
    assert client.post(path + "research-source", json=body).status_code == 404
