# ruff: noqa: F811 -- imported pytest fixture
from career.db import Record
from test_api import client  # noqa: F401


def test_manual_structure_http_is_selective_and_user_scoped(client):
    client.headers["Authorization"] = "Bearer alice-key"
    e = client.post(
        "/api/evidence",
        json={"title": "Fixture", "body": "I designed a test", "source_title": "fixture", "confirmed": True},
    ).json()
    proposal = client.post(
        f"/api/evidence/{e['id']}/extract",
        json={
            "manual": {
                "items": [
                    {
                        "kind": "Project",
                        "quote": "I designed a test",
                        "payload_json": '{"name":"Fixture","summary":"I designed a test"}',
                    },
                    {
                        "kind": "Ownership",
                        "quote": "I designed a test",
                        "payload_json": '{"implementation":"UNKNOWN"}',
                    },
                ],
                "missing_information": ["scope"],
            }
        },
    )
    assert proposal.status_code == 200
    p = proposal.json()
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.post(f"/api/extractions/{p['id']}/apply", json={"confirmed": True}).status_code == 404
    client.headers["Authorization"] = "Bearer alice-key"
    result = client.post(
        f"/api/extractions/{p['id']}/apply",
        json={
            "confirmed": True,
            "selections": [
                {"index": 1, "data": {**p["data"]["items"][1]["data"], "implementation": "USER_AI_ASSISTED"}}
            ],
        },
    )
    assert result.status_code == 200 and len(result.json()["entity_ids"]) == 1


def test_reference_routes_do_not_expose_other_users(client):
    from career.api import database
    from career.references import register

    session = next(client.app.dependency_overrides[database]())
    r = register(session, "alice", "integrity", "# private reference")
    session.commit()
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get("/api/references").json() == []
    assert client.get(f"/api/references/{r.id}").status_code == 404
    assert client.post(f"/api/references/{r.id}/activation", json={"active": False}).status_code == 404
    client.headers["Authorization"] = "Bearer alice-key"
    assert "content" not in client.get("/api/references").json()[0]
    assert client.get(f"/api/references/{r.id}").json()["data"]["content"] == "# private reference"
    assert client.post(f"/api/references/{r.id}/activation", json={"active": False}).status_code == 200


def test_revision_receipts_cannot_be_read_from_another_workspace(client):
    from career.api import database

    session = next(client.app.dependency_overrides[database]())
    r = Record(
        user_id="alice", kind="RevisionProposal", data={"workspace_id": "private", "status": "PENDING"}
    )
    session.add(r)
    session.commit()
    client.headers["Authorization"] = "Bearer bob-key"
    assert (
        client.post(
            f"/api/applications/private/revision-proposals/{r.id}", json={"decision": "REJECT"}
        ).status_code
        == 404
    )
