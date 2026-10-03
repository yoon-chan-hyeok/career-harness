# ruff: noqa: F811 -- reuse the isolated authenticated API fixture
import base64
from datetime import timedelta
from types import SimpleNamespace

from career.api import app, database
from career.db import now
from career.models import PromptRun
from test_api import client  # noqa: F401


def test_document_upload_original_download_and_delete_are_private(client):
    value = "합성 자료입니다. 직접 확인 전에는 사실 근거로 사용하지 않습니다.".encode()
    body = {"filename": "synthetic.txt", "content_base64": base64.b64encode(value).decode()}
    assert client.post("/api/sources/upload", json=body).status_code == 401
    client.headers["Authorization"] = "Bearer alice-key"
    result = client.post("/api/sources/upload", json=body)
    assert result.status_code == 200
    ident = result.json()["id"]
    path = f"/api/sources/uploads/{ident}"
    assert client.get(path + "/original").content == value
    assert "original_base64" not in str(client.get("/api/sources").json())
    assert client.get("/api/evidence").json() == []
    confirmed = client.post(path + "/confirm", json={"title": "합성 경험", "confirmed": True})
    assert confirmed.status_code == 200 and confirmed.json()["evidence"]["status"] == "UNVERIFIED"
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get(path + "/original").status_code == 404
    client.headers["Authorization"] = "Bearer alice-key"
    assert client.delete(f"/api/sources/{ident}").status_code == 200
    assert client.get(path + "/original").status_code == 404


def test_provider_activity_distinguishes_actual_workspace_response_from_probe(client, monkeypatch):
    import career.upgrade_routes as routes

    monkeypatch.setattr(routes, "provider_settings", lambda: SimpleNamespace(provider="huggingface", model="synthetic/model"))
    client.headers["Authorization"] = "Bearer alice-key"
    assert client.get("/api/providers/activity").json()["last_success"] is None
    generator = app.dependency_overrides[database]()
    db = next(generator)
    instant = now()
    common = {"status": "COMPLETED", "model": "synthetic/model", "workspace_id": "synthetic-w", "latency_ms": 150}
    db.add_all([
        PromptRun(user_id="alice", stage="resume_writer", provider="HuggingFace", data=common, created_at=instant),
        PromptRun(user_id="bob", stage="resume_writer", provider="HuggingFace", data={**common, "model": "private-model"}, created_at=instant + timedelta(seconds=3)),
        PromptRun(user_id="alice", stage="provider_connection_check", provider="HuggingFace", data=common, created_at=instant + timedelta(seconds=2)),
        PromptRun(user_id="alice", stage="resume_writer", provider="HuggingFace", data={**common, "status": "FAILED"}, created_at=instant + timedelta(seconds=1)),
    ])
    db.commit()
    generator.close()
    result = client.get("/api/providers/activity").json()["last_success"]
    assert result["model"] == "synthetic/model" and result["stage"] == "resume_writer"
    assert result["provider"] == "huggingface" and result["current_configuration_matches"]
    assert "private-model" not in str(result)
    monkeypatch.setattr(routes, "provider_settings", lambda: SimpleNamespace(provider="groq", model="new-model"))
    assert not client.get("/api/providers/activity").json()["last_success"]["current_configuration_matches"]
