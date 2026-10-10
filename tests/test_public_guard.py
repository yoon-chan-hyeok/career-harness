from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from career.api import app, database
from career.db import Base
from career.models import RequestRateBucket, Workspace
from career.public_guard import limit_request
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from test_public_service import public_env  # noqa: F401


def test_request_limit_is_atomic_and_per_user(public_env, monkeypatch, tmp_path):  # noqa: F811
    engine = create_engine("sqlite:///" + (tmp_path / "limits.db").as_posix())
    Base.metadata.create_all(engine)
    monkeypatch.setenv("CAREER_PUBLIC_REQUESTS_PER_MINUTE", "3")
    monkeypatch.setenv("CAREER_PUBLIC_MUTATIONS_PER_MINUTE", "2")
    monkeypatch.setattr("career.public_guard.time.time", lambda: 6000)
    barrier = Barrier(8)

    def call(_):
        barrier.wait()
        try:
            limit_request(engine, "owner", "POST")
            return 200
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        result = list(pool.map(call, range(8)))
    assert result.count(200) == 2 and result.count(429) == 6
    limit_request(engine, "owner", "GET")
    with pytest.raises(HTTPException):
        limit_request(engine, "owner", "GET")
    limit_request(engine, "other", "POST")
    monkeypatch.setattr("career.public_guard.time.time", lambda: 6060)
    limit_request(engine, "owner", "POST")
    with Session(engine) as db:
        bucket = db.get(RequestRateBucket, "owner")
        assert bucket is not None and bucket.requests == 1
    engine.dispose()


def test_http_public_join_consent_and_transaction_failure_before_success(public_env, monkeypatch, tmp_path):  # noqa: F811
    engine = create_engine("sqlite:///" + (tmp_path / "public-api.db").as_posix())
    Base.metadata.create_all(engine)
    subject = str(uuid4())
    monkeypatch.setattr("career.api.authenticate", lambda _: subject)
    monkeypatch.setattr("career.public_service.verify_confirmed_email", lambda *args: None)
    monkeypatch.setenv("CAREER_PUBLIC_MAX_APPLICATIONS", "1")

    def sessions(request: Request):
        with Session(engine, expire_on_commit=False) as db:
            db.info["career_request_method"] = request.method
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[database] = sessions
    try:
        with TestClient(app) as client:
            assert client.get('/api/service/public').json()['access_mode'] == 'public'
            assert client.get('/api/account/onboarding').json()['required']
            assert client.get('/api/applications').status_code == 403
            assert client.get('/api/export').status_code == 200
            assert client.post('/api/account/onboarding', json={'accepted':True,'policy_version':'outdated'}).status_code == 409
            assert client.post('/api/account/onboarding', json={'accepted':True,'policy_version':'2026-10-05'}).status_code == 200
            body = {'company':'Synthetic','role':'Research','jd_raw':'Evaluation'}
            assert client.post('/api/applications', json=body).status_code == 200
            assert client.post('/api/applications', json=body).status_code == 409
            with Session(engine) as db:
                assert db.scalar(select(func.count()).select_from(Workspace)) == 1
            monkeypatch.setenv('CAREER_POLICY_VERSION','2026-10-06')
            assert client.get('/api/applications').status_code == 403
            assert client.get('/api/account').status_code == 200
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
