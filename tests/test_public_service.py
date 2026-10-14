import json
import time
from typing import Any
from uuid import uuid4

import httpx
import pytest
from career.authentication import (
    SupabaseVerifier,
    authenticate,
    authentication_configuration,
    require_recent_otp,
)
from career.db import Record
from career.models import ServiceMember
from career.public_service import (
    DEFAULT_PUBLIC_LIMITS,
    POLICY_RECORD_KIND,
    accept_policy,
    ensure_public_member,
    onboarding_status,
    public_service_configuration,
    require_public_consent,
    validate_public_settings,
    verify_confirmed_email,
)
from career.service_access import access_mode, configure_member, require_member, shared_service
from fastapi import HTTPException
from sqlalchemy import func, select
from test_production_security import issued, signing  # noqa: F401


@pytest.fixture
def public_env(monkeypatch):
    monkeypatch.setenv("CAREER_ENV", "test")
    monkeypatch.setenv("CAREER_ACCESS_MODE", "public")
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("AUTH_TOKENS", "{}")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_synthetic-test")
    monkeypatch.setenv("CAREER_ALLOWED_USER_IDS", "")
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", "")
    monkeypatch.setenv("CAREER_REGISTRATION_OPEN", "1")
    monkeypatch.setenv("CAREER_POLICY_VERSION", "2026-10-05")


def confirmed_user(user: str, **changes):
    return {"id": user, "email": "synthetic@example.test", "email_confirmed_at": "2026-10-01T00:00:00Z",
            "is_anonymous": False, **changes}


def test_public_mode_requires_supabase_and_invalid_access_fails_closed(public_env, monkeypatch):
    assert shared_service()
    assert authentication_configuration().require_nonanonymous
    monkeypatch.setenv("AUTH_MODE", "local")
    with pytest.raises(ValueError, match="Supabase"):
        authentication_configuration()
    monkeypatch.setenv("CAREER_ACCESS_MODE", "public-typo")
    with pytest.raises(ValueError):
        access_mode()
    with pytest.raises(HTTPException) as error:
        authenticate("Bearer unknown")
    assert error.value.status_code == 503


@pytest.mark.parametrize("anonymous", [None, True, "false", 0])
def test_public_jwt_requires_explicit_signed_nonanonymous(public_env, signing, monkeypatch, anonymous):  # noqa: F811
    private, key = signing
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"keys": [key]}))
    monkeypatch.setattr("career.authentication.configured_verifier", lambda config: SupabaseVerifier(config, transport))
    token, _ = issued(private, is_anonymous=anonymous)
    with pytest.raises(HTTPException) as error:
        authenticate("Bearer " + token)
    assert error.value.status_code == 401
    token, claims = issued(private, is_anonymous=False)
    assert authenticate("Bearer " + token) == claims["sub"]


def test_email_confirmation_only_trusts_fixed_auth_endpoint(public_env):
    subject = str(uuid4())
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=confirmed_user(subject))

    verify_confirmed_email(subject, "Bearer synthetic-token", httpx.MockTransport(respond))
    assert len(calls) == 1
    assert str(calls[0].url) == "https://example.supabase.co/auth/v1/user"
    assert calls[0].headers["authorization"] == "Bearer synthetic-token"
    assert calls[0].headers["apikey"] == "sb_publishable_synthetic-test"


@pytest.mark.parametrize("changes", [
    {"email_confirmed_at": None, "user_metadata": {"email_verified": True, "email_confirmed_at": "2026-10-01"}},
    {"email_confirmed_at": "not-a-date"}, {"email": ""}, {"id": str(uuid4())},
    {"is_anonymous": True}, {"is_anonymous": "false"},
])
def test_metadata_cannot_forge_verified_email(public_env, changes):
    subject = str(uuid4())
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=confirmed_user(subject, **changes)))
    with pytest.raises(HTTPException) as error:
        verify_confirmed_email(subject, "Bearer synthetic-token", transport)
    assert error.value.status_code == 403


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_auth_outage_and_redirect_are_redacted(public_env, status):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, text="private-sensitive-response", headers={"location": "https://attacker.test/"})

    with pytest.raises(HTTPException) as error:
        verify_confirmed_email(str(uuid4()), "Bearer synthetic-token", httpx.MockTransport(respond))
    assert len(calls) == 1
    assert "private-sensitive-response" not in str(error.value.detail)
    assert error.value.status_code == (401 if status in {401, 403} else 503)


def test_first_public_admission_saves_limits_once_and_suspension_wins(public_env, db, monkeypatch):
    subject, other = str(uuid4()), str(uuid4())
    calls = []
    monkeypatch.setattr("career.public_service.verify_confirmed_email", lambda user, auth: calls.append(user))
    ensure_public_member(db, subject, "Bearer verified")
    db.commit()
    assert db.get(ServiceMember, subject).limits == DEFAULT_PUBLIC_LIMITS
    ensure_public_member(db, subject, "Bearer verified")
    assert calls == [subject]
    monkeypatch.setenv("CAREER_REGISTRATION_OPEN", "0")
    ensure_public_member(db, subject, "Bearer verified")
    with pytest.raises(HTTPException):
        ensure_public_member(db, other, "Bearer verified")
    assert calls == [subject]
    member = db.get(ServiceMember, subject)
    member.status = "SUSPENDED"
    db.commit()
    with pytest.raises(HTTPException):
        ensure_public_member(db, subject, "Bearer verified")
    assert calls == [subject]


def test_suspension_created_during_email_lookup_is_not_overwritten(public_env, db, monkeypatch):
    subject = str(uuid4())

    def suspend(user, auth):
        db.add(ServiceMember(user_id=user, status="SUSPENDED", limits=DEFAULT_PUBLIC_LIMITS))
        db.commit()

    monkeypatch.setattr("career.public_service.verify_confirmed_email", suspend)
    with pytest.raises(HTTPException):
        ensure_public_member(db, subject, "Bearer verified")
    assert db.get(ServiceMember, subject).status == "SUSPENDED"


def test_public_bootstrap_subject_still_needs_admission(public_env, db, monkeypatch):
    subject = str(uuid4())
    monkeypatch.setenv("CAREER_ALLOWED_USER_IDS", subject)
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", subject)
    with pytest.raises(HTTPException):
        require_member(db, subject)


def test_consent_is_versioned_owned_and_idempotent(public_env, db, monkeypatch):
    subject, other = str(uuid4()), str(uuid4())
    db.add(ServiceMember(user_id=subject, status="ACTIVE", limits=DEFAULT_PUBLIC_LIMITS))
    db.flush()
    with pytest.raises(HTTPException) as error:
        require_public_consent(db, subject)
    detail: Any = error.value.detail
    assert detail["code"] == "POLICY_ACCEPTANCE_REQUIRED"
    with pytest.raises(HTTPException):
        accept_policy(db, subject, "stale")
    assert accept_policy(db, subject, "2026-10-05")["accepted"]
    accept_policy(db, subject, "2026-10-05")
    assert db.scalar(select(func.count()).select_from(Record).where(Record.kind == POLICY_RECORD_KIND)) == 1
    require_public_consent(db, subject)
    assert onboarding_status(db, other)["required"]
    monkeypatch.setenv("CAREER_POLICY_VERSION", "2026-10-06")
    assert onboarding_status(db, subject)["required"]
    monkeypatch.setenv("CAREER_ACCESS_MODE", "invite")
    require_public_consent(db, subject)


def test_deleted_account_cannot_be_reactivated(public_env, db, monkeypatch):
    subject, operator = str(uuid4()), str(uuid4())
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", operator)
    db.add(ServiceMember(user_id=subject, status="SUSPENDED", limits=DEFAULT_PUBLIC_LIMITS))
    db.add(Record(user_id=subject, kind="AccountDeletionReceipt", data={"phase": "ACCESS_CLOSED"}))
    db.flush()
    with pytest.raises(ValueError, match="활성화"):
        configure_member(db, operator, subject, "ACTIVE", {})


def test_public_configuration_is_explicit_allowlist_without_keys(public_env, monkeypatch):
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_should-not-appear")
    config = public_service_configuration()
    assert config["access_mode"] == "public" and config["registration_open"]
    assert config["retention_days"] is None
    assert set(config) == {"access_mode", "registration_open", "service_name", "policy_version", "operator_name",
                           "support_email", "privacy_url", "terms_url", "captcha_site_key", "public_limits",
                           "retention_days", "backup_retention_days", "ai_provider",
                           "guest_enabled", "guest_session_seconds", "support_url"}
    assert "sb_secret" not in json.dumps(config)


def test_production_public_setup_requires_real_operator_and_provider_attestations(public_env, monkeypatch):
    monkeypatch.setenv("CAREER_ENV", "production")
    required = {
        "CAREER_OPERATOR_NAME": "Synthetic Operator", "CAREER_SUPPORT_EMAIL": "support@example.test",
        "CAREER_CAPTCHA_SITE_KEY": "synthetic-turnstile-site-key",
        "CAREER_CAPTCHA_ENABLED_CONFIRMED": "1", "CAREER_SMTP_CONFIGURED_CONFIRMED": "1",
        "CAREER_EMAIL_CONFIRMATION_CONFIRMED": "1", "SUPABASE_SECRET_KEY": "sb_secret_synthetic-only",
        "CAREER_BACKUP_RETENTION_DAYS": "14",
    }
    for name, value in required.items():
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError):
        validate_public_settings()
    for name, value in required.items():
        monkeypatch.setenv(name, value)
    validate_public_settings()
    for name in required:
        value = required[name]
        monkeypatch.delenv(name)
        with pytest.raises(ValueError):
            validate_public_settings()
        monkeypatch.setenv(name, value)


def test_recent_otp_uses_signed_amr_not_new_token_iat(public_env, signing, monkeypatch):  # noqa: F811
    private, key = signing
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"keys": [key]}))
    monkeypatch.setattr("career.authentication.configured_verifier", lambda config: SupabaseVerifier(config, transport))
    email_calls = []
    monkeypatch.setattr("career.public_service.verify_confirmed_email", lambda user, auth: email_calls.append(user))
    subject = str(uuid4())
    for amr in [[], [{"method": "otp", "timestamp": time.time() - 600}],
                [{"method": "password", "timestamp": time.time()}],
                [{"method": "otp", "timestamp": time.time() + 600}],
                [{"method": "otp", "timestamp": str(time.time())}]]:
        token, _ = issued(private, sub=subject, is_anonymous=False, amr=amr, iat=int(time.time()))
        with pytest.raises(HTTPException):
            require_recent_otp("Bearer " + token, subject)
    assert email_calls == []
    token, _ = issued(private, sub=subject, is_anonymous=False,
                      amr=[{"method": "otp", "timestamp": int(time.time())}])
    require_recent_otp("Bearer " + token, subject)
    assert email_calls == [subject]
    with pytest.raises(HTTPException):
        require_recent_otp("Bearer " + token, str(uuid4()))


def test_public_operator_members_are_bounded_searchable_and_never_bootstrap_unregistered(public_env, db, monkeypatch):
    from career.service_access import service_status

    operator = str(uuid4())
    monkeypatch.setenv("CAREER_ADMIN_USER_IDS", operator)
    users = sorted(str(uuid4()) for _ in range(121))
    for user in users:
        db.add(ServiceMember(user_id=user, status="ACTIVE", limits=DEFAULT_PUBLIC_LIMITS))
    db.flush()
    first = service_status(db, operator)
    assert len(first["members"]) == 50 and first["total_members"] == 121
    second = service_status(db, operator, after=first["next_cursor"])
    third = service_status(db, operator, after=second["next_cursor"])
    assert [row["user_id"] for page in (first, second, third) for row in page["members"]] == users
    assert third["next_cursor"] is None
    assert service_status(db, operator, prefix=users[5])["members"][0]["user_id"] == users[5]
    assert service_status(db, operator, prefix="%")["members"] == []


@pytest.mark.parametrize("modern,legacy,valid", [
    ("modern", "", True), ("", "legacy", True),
    ("legacy", "", False), ("", "modern", False),
    ("sb_secret_", "", False), ("invalid-secret", "legacy", False),
])
def test_startup_and_deletion_agree_on_key_slot(public_env, monkeypatch, modern, legacy, valid):
    import jwt
    from career.account_lifecycle import admin_configuration

    keys = {"modern": "sb_secret_synthetic-test", "legacy": jwt.encode({"role": "service_role"}, "synthetic-" * 8)}
    for name, value in {
        "CAREER_ENV": "production", "CAREER_OPERATOR_NAME": "Synthetic Operator",
        "CAREER_SUPPORT_EMAIL": "qa@example.test", "CAREER_BACKUP_RETENTION_DAYS": "14",
        "CAREER_CAPTCHA_SITE_KEY": "synthetic-site-key", "CAREER_CAPTCHA_ENABLED_CONFIRMED": "1",
        "CAREER_SMTP_CONFIGURED_CONFIRMED": "1", "CAREER_EMAIL_CONFIRMATION_CONFIRMED": "1",
        "SUPABASE_SECRET_KEY": keys.get(modern, modern), "SUPABASE_SERVICE_ROLE_KEY": keys.get(legacy, legacy),
    }.items():
        monkeypatch.setenv(name, value)
    if valid:
        validate_public_settings()
        assert admin_configuration().legacy == (not modern)
    else:
        with pytest.raises(ValueError):
            validate_public_settings()
        with pytest.raises(HTTPException) as error:
            admin_configuration()
        assert error.value.status_code == 503
