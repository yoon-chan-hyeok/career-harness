import json
from uuid import uuid4

import httpx
import pytest
from career.account_lifecycle import DeletionPending, account_status, delete_account
from career.db import Base, Record
from career.models import AIUsageBucket, ServiceMember, Source
from career.public_guard import bind_request
from career.truth import register_source
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from test_public_service import public_env  # noqa: F401


@pytest.fixture
def accounts(public_env, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_synthetic-delete-only")
    monkeypatch.setattr("career.account_lifecycle.require_recent_otp", lambda *args: None)
    engine = create_engine("sqlite:///" + (tmp_path / "accounts.db").as_posix())
    Base.metadata.create_all(engine)
    own, other = str(uuid4()), str(uuid4())
    with Session(engine) as db:
        for user in (own, other):
            db.add(ServiceMember(user_id=user, status="ACTIVE", limits={}))
            register_source(db, user, "synthetic.txt", "private synthetic text " + user, "MEMORY")
            db.add(Record(user_id=user, kind="Conversation", data={"text": user}))
            db.add(AIUsageBucket(user_id=user, period="D:2026-10-05", data={"calls": 2}))
        db.commit()
    yield engine, own, other
    engine.dispose()


def test_delete_purges_only_owner_and_keeps_conservative_accounting(accounts):
    engine, own, other = accounts
    calls = []

    def remove(request):
        calls.append(request)
        assert request.method == "DELETE"
        assert request.url == "https://example.supabase.co/auth/v1/admin/users/" + own
        assert json.loads(request.content) == {"should_soft_delete": False}
        assert request.headers["apikey"] == "sb_secret_synthetic-delete-only"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={})

    with Session(engine) as db:
        result = delete_account(db, own, "DELETE", "synthetic-fresh-otp", transport=httpx.MockTransport(remove))
        assert result["status"] == "DELETED"
        member = db.get(ServiceMember, own)
        assert member is not None and member.status == "SUSPENDED"
        assert not list(db.scalars(select(Source).where(Source.user_id == own)))
        assert len(list(db.scalars(select(Source).where(Source.user_id == other)))) == 1
        assert {r.kind for r in db.scalars(select(Record).where(Record.user_id == own))} == {"AccountDeletionReceipt"}
        bucket = db.scalar(select(AIUsageBucket).where(AIUsageBucket.user_id == own))
        assert bucket is not None and bucket.data["calls"] == 2
    assert len(calls) == 1


def test_external_failure_is_retryable_closed_and_redacted(accounts):
    engine, own, _ = accounts
    with Session(engine) as db:
        with pytest.raises(DeletionPending) as error:
            delete_account(db, own, "DELETE", "fresh", transport=httpx.MockTransport(
                lambda _: httpx.Response(500, text="private-secret-provider-body")))
        assert error.value.payload["career_data_deleted"]
        assert "private-secret" not in str(error.value)
        assert account_status(db, own)["status"] == "CLOSED"
        db.rollback()
        result = delete_account(db, own, "DELETE", "fresh", transport=httpx.MockTransport(
            lambda _: httpx.Response(404, json={"code": "user_not_found"})))
        assert result["status"] == "DELETED"


def test_wrong_confirmation_or_unverified_otp_never_closes_account(accounts, monkeypatch):
    engine, own, _ = accounts
    with Session(engine) as db:
        with pytest.raises(HTTPException):
            delete_account(db, own, "wrong", "fresh")
        monkeypatch.setattr("career.account_lifecycle.require_recent_otp", lambda *args: (_ for _ in ()).throw(HTTPException(401)))
        with pytest.raises(HTTPException):
            delete_account(db, own, "DELETE", "old")
        member = db.get(ServiceMember, own)
        assert member is not None and member.status == "ACTIVE"


def test_late_flushed_writer_cannot_resurrect_deleted_data(accounts):
    engine, own, _ = accounts
    with Session(engine, expire_on_commit=False) as writer:
        cached = writer.get(ServiceMember, own)
        assert cached is not None
        writer.commit()
        with Session(engine) as closer:
            delete_account(closer, own, "DELETE", "fresh", transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={})))
        assert cached.status == "ACTIVE"  # The final fence must refresh, not trust this cached object.
        bind_request(writer, own)
        writer.add(Record(user_id=own, kind="Conversation", data={"text": "late response"}))
        writer.flush()
        with pytest.raises(HTTPException) as error:
            writer.commit()
        assert error.value.status_code == 403
        writer.rollback()
    with Session(engine) as db:
        assert not db.scalar(select(Record).where(Record.user_id == own, Record.kind == "Conversation"))
