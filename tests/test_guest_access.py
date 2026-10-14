"""Public trial identities, quotas, revocation and data isolation."""
# ruff: noqa: F811 -- shared isolated HTTP fixture
from datetime import timedelta
from uuid import uuid4

import jwt
import pytest
from career.api import app, database
from career.authentication import authentication_configuration
from career.db import Record, now
from career.guest_access import LIFETIME, SESSION_KIND, cleanup_expired
from career.models import RequestRateBucket
from career.public_service import validate_public_settings
from sqlalchemy import select
from test_api import client  # noqa: F401


@pytest.fixture
def guest_env(monkeypatch):
    monkeypatch.setenv("CAREER_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "guest")
    monkeypatch.setenv("AUTH_TOKENS", "{}")
    monkeypatch.setenv("CAREER_ACCESS_MODE", "public")
    monkeypatch.setenv("CAREER_REGISTRATION_OPEN", "1")
    monkeypatch.setenv("CAREER_GUEST_SESSION_SECRET", "synthetic-test-only-" + "a" * 64)
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", "")
    monkeypatch.setenv("CAREER_ALLOWED_USER_IDS", "")
    monkeypatch.setenv("CAREER_LLM_PROVIDER", "none")
    monkeypatch.setenv("CAREER_REQUIRE_AI", "0")
    monkeypatch.setenv("CAREER_POLICY_VERSION", "synthetic-guest-1")
    monkeypatch.delenv("VERCEL", raising=False)


def begin(client):
    response = client.post("/api/auth/guest")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["expires_in"] == LIFETIME and "refresh_token" not in result
    return result["access_token"]


def headers(token):
    return {"Authorization": "Bearer " + token}


def agree(client, token):
    response = client.post("/api/account/onboarding", headers=headers(token),
                           json={"policy_version": "synthetic-guest-1", "accepted": True})
    assert response.status_code == 200, response.text


def test_guest_http_workspaces_are_private_consent_required_and_removable(client, guest_env):
    a, b = begin(client), begin(client)
    assert a != b
    assert client.get("/api/auth/config").json() == {"provider": "guest"}
    assert client.get("/api/service/public").json()["guest_enabled"]
    assert client.get("/api/applications", headers=headers(a)).status_code == 403
    assert client.get("/api/account", headers=headers(a)).json()["requires_recent_email_otp"] is False
    for token in (a, b):
        agree(client, token)
    created = client.post("/api/applications", headers=headers(a),
                          json={"company": "Synthetic", "role": "Analyst", "jd_raw": "Reports"})
    assert created.status_code == 200, created.text
    path = "/api/applications/" + created.json()["id"]
    assert client.get(path, headers=headers(a)).status_code == 200
    assert client.get(path, headers=headers(b)).status_code == 404
    assert client.get("/api/applications", headers=headers(b)).json() == []
    assert client.get("/api/admin/status", headers=headers(a)).status_code == 403
    assert client.post("/api/providers/configure", headers=headers(a), json={
        "provider": "none", "model": "", "token": "", "free_only_confirmed": False}).status_code == 403
    assert client.post("/api/account/delete", headers=headers(a),
                       json={"confirmation": "DELETE", "reauthentication_token": b}).status_code == 401
    removed = client.post("/api/account/delete", headers=headers(a),
                          json={"confirmation": "DELETE", "reauthentication_token": a})
    assert removed.status_code == 200 and removed.json()["status"] == "DELETED", removed.text
    assert client.get(path, headers=headers(a)).status_code == 401
    assert client.get("/api/applications", headers=headers(b)).status_code == 200


@pytest.mark.parametrize("change", ["signature", "expiry", "issuer", "audience", "subject", "lifetime", "guest", "nonce", "unregistered"])
def test_guest_forgery_or_invalid_claims_never_authenticate(client, guest_env, monkeypatch, change):
    token = begin(client)
    claims = jwt.decode(token, options={"verify_signature": False})
    if change == "expiry":
        claims["iat"], claims["exp"] = 0, LIFETIME
    if change == "issuer":
        claims["iss"] = "https://attacker.invalid"
    if change == "audience":
        claims["aud"] = "authenticated"
    if change == "subject":
        claims["sub"] = "__career_shared_budget__"
    if change == "lifetime":
        claims["exp"] += 100
    if change == "guest":
        claims["guest"] = "true"
    if change == "nonce":
        claims["jti"] = "a" * 64
    if change == "unregistered":
        claims["sub"] = str(uuid4())
    key = "wrong-" + "b" * 64 if change == "signature" else "synthetic-test-only-" + "a" * 64
    forged = jwt.encode(claims, key, algorithm="HS256")
    assert client.get("/api/account", headers=headers(forged)).status_code == 401


def test_guest_admission_global_counter_survives_session_deletion(client, guest_env):
    token = begin(client)
    generator = app.dependency_overrides[database]()
    db = next(generator)
    global_bucket = db.get(RequestRateBucket, "__career_guest_global__")
    global_bucket.requests = 100
    db.commit()
    generator.close()
    assert client.post("/api/auth/guest").status_code == 429
    agree(client, token)
    assert client.post("/api/account/delete", headers=headers(token),
                       json={"confirmation": "DELETE", "reauthentication_token": token}).status_code == 200
    assert client.post("/api/auth/guest").status_code == 429


def test_guest_network_daily_cap_cannot_be_spoofed_by_forwarded_header(client, guest_env):
    for _ in range(20):
        begin(client)
    assert client.post("/api/auth/guest", headers={"x-vercel-forwarded-for": "1.2.3.4", "x-forwarded-for": "5.6.7.8"}).status_code == 429


def test_expired_guest_cleanup_only_purges_guest_data(client, guest_env):
    a, b = begin(client), begin(client)
    agree(client, a)
    agree(client, b)
    user_a = jwt.decode(a, options={"verify_signature": False})["sub"]
    generator = app.dependency_overrides[database]()
    db = next(generator)
    row = db.scalar(select(Record).where(Record.user_id == user_a, Record.kind == SESSION_KIND))
    row.created_at = now() - timedelta(seconds=LIFETIME + 10)
    db.commit()
    bind = db.get_bind()
    generator.close()
    assert cleanup_expired(bind) == 1
    assert client.get("/api/account", headers=headers(a)).status_code == 401
    assert client.get("/api/account", headers=headers(b)).status_code == 200


@pytest.mark.parametrize("settings", [{"CAREER_GUEST_SESSION_SECRET": "short"}, {"CAREER_ACCESS_MODE": "invite"},
    {"CAREER_ADMIN_USER_IDS": str(uuid4())}, {"AUTH_TOKENS": '{"unsafe":"owner"}'}, {"CAREER_ALLOWED_USER_IDS": str(uuid4())}])
def test_guest_startup_rejects_unsafe_configuration(guest_env, monkeypatch, settings):
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        authentication_configuration()


def test_email_public_requirements_remain_separate_from_guest_trial(guest_env, monkeypatch):
    monkeypatch.setenv("CAREER_ENV", "production")
    monkeypatch.setenv("CAREER_OPERATOR_NAME", "Synthetic")
    monkeypatch.setenv("CAREER_SUPPORT_EMAIL", "synthetic@example.test")
    monkeypatch.setenv("CAREER_BACKUP_RETENTION_DAYS", "0")
    monkeypatch.setenv("CAREER_SOURCE_REPOSITORY_URL", "https://github.com/example/synthetic")
    validate_public_settings()
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_fixture")
    with pytest.raises(ValueError, match="CAPTCHA"):
        validate_public_settings()
