# ruff: noqa: F811 -- reusable API fixture
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from career.provider_policy import BudgetExceeded, StagePolicy
from career.service_access import SHARED_BUDGET_USER, configure_member, service_status
from career.usage_limits import configure_usage, request_budget_scope, usage_status
from sqlalchemy.orm import Session
from test_api import client  # noqa: F401
from test_usage_limits import ledger


@pytest.mark.parametrize("mode", ["historical", "ablation", "workflow_ablation"])
def test_shared_service_disables_excluded_external_experiments(client, monkeypatch, mode):
    monkeypatch.setenv("CAREER_SHARED_SERVICE", "1")
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", "alice")
    monkeypatch.setattr("career.providers.OpenAIProvider", lambda: pytest.fail("External experiment started"))
    client.headers["Authorization"] = "Bearer alice-key"
    assert client.post("/api/evals/run", json={"mode": mode, "confirmed_external_eval": True}).status_code == 403


def test_shared_mcp_checks_membership_with_a_real_session(client, monkeypatch):
    from contextlib import contextmanager

    from career.api import app, database
    from career.mcp_server import identity

    @contextmanager
    def session():
        generator = app.dependency_overrides[database]()
        try:
            yield next(generator)
        finally:
            generator.close()

    monkeypatch.setattr("career.mcp_server.SessionLocal", session)
    monkeypatch.setenv("CAREER_SHARED_SERVICE", "1")
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", "alice")
    monkeypatch.setenv("CAREER_MCP_TOKEN", "alice-key")
    assert identity() == "alice"
    monkeypatch.setenv("CAREER_MCP_TOKEN", "bob-key")
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        identity()


def test_upload_count_ceiling_is_shared_and_duplicates_do_not_consume_extra(client, monkeypatch):
    from test_upgrade_documents import upload_body

    monkeypatch.setenv("CAREER_SHARED_SERVICE", "1")
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", "alice,bob")
    monkeypatch.setenv("CAREER_SHARED_UPLOAD_COUNT", "1")
    client.headers["Authorization"] = "Bearer alice-key"
    body = upload_body("one.txt", b"synthetic input").model_dump()
    first = client.post("/api/sources/upload", json=body)
    assert first.status_code == 200
    assert client.post("/api/sources/upload", json=body).json()["id"] == first.json()["id"]
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.post("/api/sources/upload", json=body).status_code == 409
    assert client.get("/api/sources").json() == []


def test_invites_deny_by_default_revoke_existing_token_and_protect_operator_routes(client, monkeypatch):
    monkeypatch.setenv("CAREER_SHARED_SERVICE", "1")
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", "alice")
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get("/api/applications").status_code == 403
    client.headers["Authorization"] = "Bearer alice-key"
    body = {"user_id": "bob", "status": "ACTIVE", "limits": {"daily_calls": 4}}
    assert client.put("/api/admin/service/members", json=body).status_code == 200
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get("/api/applications").status_code == 200
    assert client.get("/api/admin/service").status_code == 403
    assert client.put("/api/admin/service/limits", json={"daily_calls": 500}).status_code == 403
    assert client.put("/api/usage/limits", json={"daily_calls": 5}).status_code == 409
    assert client.put("/api/usage/limits", json={"daily_calls": 2}).status_code == 200
    client.headers["Authorization"] = "Bearer alice-key"
    assert client.put("/api/admin/service/members", json={**body, "status": "SUSPENDED"}).status_code == 200
    client.headers["Authorization"] = "Bearer bob-key"
    assert client.get("/api/applications").status_code == 403


def test_operator_cap_applies_to_existing_larger_personal_setting(tmp_path, monkeypatch):
    engine = ledger(tmp_path)
    with Session(engine) as db:
        configure_usage(db, "bob", {"daily_calls": 1000000})
        db.commit()
        monkeypatch.setenv("CAREER_SHARED_SERVICE", "1")
        monkeypatch.setenv("CAREER_ADMIN_USER_IDS", "alice")
        configure_member(db, "alice", "bob", "ACTIVE", {"daily_calls": 2, "daily_cost_usd": 0.1})
        db.commit()
        assert usage_status(db, "bob")["limits"]["daily_calls"] == 2
        with pytest.raises(ValueError):
            configure_usage(db, "bob", {"daily_cost_usd": None})
    engine.dispose()


def test_shared_quota_is_atomic_across_users_and_settled_in_both_ledgers(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_SHARED_SERVICE", "1")
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", "alice")
    engine = ledger(tmp_path)
    with Session(engine) as db:
        configure_member(db, "alice", "bob", "ACTIVE", {})
        configure_usage(db, SHARED_BUDGET_USER, {"daily_calls": 1})
        db.commit()
    started = Barrier(2)

    def first():
        with Session(engine) as db, request_budget_scope(db, "alice") as quota:
            ticket = quota.draw(StagePolicy("unknown", max_output_tokens=20), 20)
            started.wait(timeout=5)
            started.wait(timeout=5)
            quota.settle_call(ticket, "unknown", {"input_tokens": 10, "output_tokens": 5})

    with ThreadPoolExecutor(max_workers=1) as executor:
        task = executor.submit(first)
        started.wait(timeout=5)
        with Session(engine) as db, pytest.raises(BudgetExceeded):
            with request_budget_scope(db, "bob"):
                pytest.fail("Global quota bypassed")
        started.wait(timeout=5)
        task.result(timeout=5)
    with Session(engine) as db:
        for user in ("alice", SHARED_BUDGET_USER):
            usage = usage_status(db, user)
            assert usage["daily"]["calls"] == 1 and usage["daily"]["tokens"] == 15
            assert usage["daily"]["reserved_calls"] == 0
        assert usage_status(db, "bob")["daily"]["calls"] == 0
        assert "shared_usage" in service_status(db, "alice")
    engine.dispose()
