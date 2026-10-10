import json
import time
from uuid import uuid4

import httpx
import jwt
import pytest
from career.authentication import (
    AuthConfiguration,
    SupabaseVerifier,
    authenticate,
    authentication_configuration,
    public_auth_configuration,
)
from career.db import database_url, make_engine
from career.production import install_security, migration_heads, readiness, validate_runtime_settings
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from jwt.algorithms import ECAlgorithm
from sqlalchemy import create_engine, text


@pytest.fixture
def signing():
    private = ec.generate_private_key(ec.SECP256R1())
    key = json.loads(ECAlgorithm.to_jwk(private.public_key()))
    key.update({"kid": "verified-key", "alg": "ES256", "use": "sig"})
    return private, key


def issued(private, **changes):
    claims = {
        "sub": str(uuid4()),
        "iss": "https://example.supabase.co/auth/v1",
        "aud": "authenticated",
        "iat": int(time.time()) - 20,
        "exp": int(time.time()) + 3600,
        "role": "authenticated",
    }
    claims.update(changes)
    return jwt.encode(claims, private, algorithm="ES256", headers={"kid": "verified-key"}), claims


def test_signed_db_invite_overrides_bootstrap_allowlist_and_revocation_is_immediate(signing, db, monkeypatch):
    from career.service_access import configure_member, require_member

    private, key = signing
    subject, bootstrap = str(uuid4()), str(uuid4())
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("CAREER_SHARED_SERVICE", "1")
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", bootstrap)
    monkeypatch.setenv("CAREER_ALLOWED_USER_IDS", bootstrap)
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"keys": [key]}))
    monkeypatch.setattr("career.authentication.configured_verifier", lambda config: SupabaseVerifier(config, transport))
    token, _ = issued(private, sub=subject)
    identity = authenticate("Bearer " + token)
    with pytest.raises(HTTPException):
        require_member(db, identity)
    configure_member(db, bootstrap, subject, "ACTIVE", {})
    require_member(db, authenticate("Bearer " + token))
    configure_member(db, bootstrap, subject, "SUSPENDED", {})
    with pytest.raises(HTTPException):
        require_member(db, authenticate("Bearer " + token))


def verifier(key, calls):
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"keys": [key]})

    return SupabaseVerifier(
        AuthConfiguration("supabase", "https://example.supabase.co/auth/v1"), httpx.MockTransport(respond)
    )


def test_supabase_verifies_signed_subject_and_caches_only_public_keys(signing):
    private, key = signing
    calls = []
    auth = verifier(key, calls)
    token, claims = issued(private)
    assert auth.verify(token) == claims["sub"]
    assert auth.verify(token) == claims["sub"]
    assert len(calls) == 1
    assert str(calls[0].url) == "https://example.supabase.co/auth/v1/.well-known/jwks.json"
    assert "authorization" not in calls[0].headers


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://attacker.example/auth/v1"},
        {"aud": "service_role"},
        {"exp": lambda: int(time.time()) - 60},
        {"iat": lambda: int(time.time()) + 60},
        {"role": "service_role"},
        {"role": "anon"},
        {"sub": "forged-owner"},
        {"is_anonymous": True},
    ],
)
def test_supabase_rejects_wrong_claims(signing, changes):
    private, key = signing
    # Measure relative times when this case runs, not during collection of a
    # suite that may take longer than the invalid token's 60-second offset.
    current_changes = {key: value() if callable(value) else value for key, value in changes.items()}
    token, _ = issued(private, **current_changes)
    with pytest.raises(HTTPException) as result:
        verifier(key, []).verify(token)
    assert result.value.status_code == 401


def test_supabase_rejects_forged_signature_and_symmetric_algorithm(signing):
    _, key = signing
    foreign = ec.generate_private_key(ec.SECP256R1())
    forged, _ = issued(foreign)
    with pytest.raises(HTTPException) as result:
        verifier(key, []).verify(forged)
    assert result.value.status_code == 401
    calls = []
    symmetric = jwt.encode(
        {"sub": str(uuid4())},
        "a-long-test-secret-not-used-in-production",
        algorithm="HS256",
        headers={"kid": "verified-key"},
    )
    with pytest.raises(HTTPException):
        verifier(key, calls).verify(symmetric)
    assert calls == []


def test_unknown_key_does_not_fetch_on_every_token(signing, monkeypatch):
    private, key = signing
    calls = []
    auth = verifier(key, calls)
    clock = [100.0]
    monkeypatch.setattr("career.authentication.time.monotonic", lambda: clock[0])
    token, _ = issued(private)
    auth.verify(token)
    unknown = jwt.encode({"sub": str(uuid4())}, private, algorithm="ES256", headers={"kid": "attacker-key"})
    for _ in range(5):
        with pytest.raises(HTTPException):
            auth.verify(unknown)
    assert len(calls) == 1
    clock[0] += 31
    with pytest.raises(HTTPException):
        auth.verify(unknown)
    assert len(calls) == 2


def test_jwks_outage_is_redacted_and_has_no_local_token_fallback(signing):
    private, _ = signing
    transport = httpx.MockTransport(lambda request: httpx.Response(503, text="private-server-error"))
    auth = SupabaseVerifier(AuthConfiguration("supabase", "https://example.supabase.co/auth/v1"), transport)
    token, _ = issued(private)
    with pytest.raises(HTTPException) as result:
        auth.verify(token)
    assert result.value.status_code == 503
    assert "private-server-error" not in str(result.value.detail)


def test_production_disallows_development_tokens(monkeypatch):
    monkeypatch.setenv("CAREER_ENV", "production")
    monkeypatch.setenv("AUTH_TOKENS", '{"private-token":"owner"}')
    monkeypatch.setenv("AUTH_MODE", "local")
    with pytest.raises(ValueError):
        authentication_configuration()
    with pytest.raises(HTTPException) as result:
        authenticate("Bearer private-token")
    assert result.value.status_code == 503


def test_public_configuration_never_returns_service_role_key(monkeypatch):
    monkeypatch.setenv("CAREER_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_secret_never-public")
    with pytest.raises(ValueError):
        public_auth_configuration()
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_public-test")
    result = public_auth_configuration()
    assert result == {
        "provider": "supabase",
        "supabase_url": "https://example.supabase.co",
        "publishable_key": "sb_publishable_public-test",
    }


def test_production_requires_tls_and_exact_hosts(monkeypatch):
    monkeypatch.setenv("CAREER_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("AUTH_TOKENS", "{}")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:very-private@db.example/postgres")
    monkeypatch.setenv("CAREER_ALLOWED_HOSTS", "api.example.com")
    with pytest.raises(ValueError) as result:
        validate_runtime_settings()
    assert "very-private" not in str(result.value)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://postgres:very-private@db.example/postgres?sslmode=verify-full"
    )
    validate_runtime_settings()
    monkeypatch.setenv("CAREER_ALLOWED_HOSTS", "*")
    with pytest.raises(ValueError):
        validate_runtime_settings()


def test_postgres_urls_use_installed_driver_and_live_pool_checks():
    parsed = database_url("postgres://postgres:p%40ss@db.example:5432/postgres?sslmode=require")
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.password == "p@ss"
    engine = make_engine(parsed.render_as_string(hide_password=False))
    assert engine.pool._pre_ping is True
    engine.dispose()


def test_readiness_distinguishes_configuration_from_live_calls(monkeypatch):
    monkeypatch.setenv("CAREER_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-config-only")
    monkeypatch.setenv("OPENAI_MODEL", "synthetic-config-only")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY)"))
        for head in migration_heads():
            connection.execute(text("INSERT INTO alembic_version VALUES (:head)"), {"head": head})
    status, report = readiness(engine)
    assert status == 200
    assert report["checks"]["llm"] == {
        "status": "configured", "live_verified": False, "provider": "openai", "verified_at": None,
    }
    assert "synthetic-config-only" not in json.dumps(report)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM alembic_version"))
    assert readiness(engine)[0] == 503
    engine.dispose()


def test_body_and_request_limits_apply_to_real_bytes(monkeypatch):
    monkeypatch.setenv("CAREER_ENV", "test")
    monkeypatch.setenv("CAREER_MAX_REQUEST_BYTES", "1024")
    monkeypatch.setenv("CAREER_RATE_LIMIT_PER_MINUTE", "3")
    monkeypatch.delenv("CAREER_ALLOWED_HOSTS", raising=False)
    app = FastAPI()
    install_security(app)

    @app.post("/api/echo")
    async def echo(request: Request):
        return {"length": len(await request.body())}

    with TestClient(app) as client:
        first = client.post("/api/echo", content=b"private-input")
        assert first.status_code == 200 and first.json()["length"] == 13
        assert first.headers["cache-control"] == "no-store"
        assert (
            client.post("/api/echo", content=b"x" * 2048, headers={"content-length": "1"}).status_code == 413
        )
        assert client.post("/api/echo", content=b"ok").status_code == 200
        limited = client.post("/api/echo", content=b"ok")
        assert limited.status_code == 429 and limited.headers["retry-after"] == "60"
