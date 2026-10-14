"""Verified public admission and versioned policy acceptance; no trust in user metadata."""

import json
import os
import re
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from career.access_config import access_mode, account_admin_key
from career.authentication import (
    AUTH_ERROR,
    authentication_configuration,
    is_production,
    public_auth_configuration,
)

DEFAULT_PUBLIC_LIMITS = {
    "daily_calls": 10, "monthly_calls": 100,
    "daily_tokens": 50000, "monthly_tokens": 300000,
    "daily_cost_usd": None, "monthly_cost_usd": None,
}
POLICY_RECORD_KIND = "ServicePolicyAccepted"


def registration_open() -> bool:
    value = os.getenv("CAREER_REGISTRATION_OPEN", "1")
    if value not in {"0", "1"}:
        raise ValueError("CAREER_REGISTRATION_OPEN must be 0 or 1")
    return access_mode() == "public" and value == "1"


def policy_version() -> str:
    value = os.getenv("CAREER_POLICY_VERSION", "2026-10-05").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
        raise ValueError("CAREER_POLICY_VERSION must be a stable version identifier")
    return value


def public_limits() -> dict[str, Any]:
    result = DEFAULT_PUBLIC_LIMITS.copy()
    for key in ("daily_calls", "monthly_calls", "daily_tokens", "monthly_tokens"):
        try:
            value = int(os.getenv("CAREER_PUBLIC_" + key.upper(), str(result[key])))
            if not 0 <= value <= 100000000:
                raise ValueError()
            result[key] = value
        except ValueError:
            raise ValueError("Public account limits must be integers from 0 to 100000000") from None
    return result


def backup_retention_days() -> int | None:
    raw = os.getenv("CAREER_BACKUP_RETENTION_DAYS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
        if not 0 <= value <= 3650:
            raise ValueError()
        return value
    except ValueError:
        raise ValueError("CAREER_BACKUP_RETENTION_DAYS must be an integer from 0 to 3650") from None


def validate_public_settings() -> None:
    if access_mode() != "public":
        return
    authentication_configuration()
    public_auth_configuration()
    registration_open()
    policy_version()
    public_limits()
    backup_retention_days()
    from career.production import integer_setting

    for setting, default, maximum in (
        ("CAREER_PUBLIC_REQUESTS_PER_MINUTE", 120, 10000),
        ("CAREER_PUBLIC_MUTATIONS_PER_MINUTE", 20, 1000),
        ("CAREER_PUBLIC_MAX_APPLICATIONS", 100, 100000),
        ("CAREER_PUBLIC_MAX_EVIDENCE", 500, 100000),
        ("CAREER_PUBLIC_MAX_SOURCES", 500, 100000),
        ("CAREER_PUBLIC_MAX_ARTIFACTS", 5000, 100000),
    ):
        integer_setting(setting, default, 1, maximum)
    if not is_production():
        return
    name = os.getenv("CAREER_OPERATOR_NAME", "").strip()
    email = os.getenv("CAREER_SUPPORT_EMAIL", "").strip()
    if not name or len(name) > 200 or any(ord(char) < 32 for char in name):
        raise ValueError("Public production requires CAREER_OPERATOR_NAME")
    if len(email) > 254 or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", email):
        raise ValueError("Public production requires CAREER_SUPPORT_EMAIL")
    from career.guest_access import enabled

    if enabled():
        from career.access_config import source_repository_url

        if source_repository_url() is None:
            raise ValueError("Guest trial requires a public CAREER_SOURCE_REPOSITORY_URL for support")
        return
    if backup_retention_days() is None:
        raise ValueError("Public production requires CAREER_BACKUP_RETENTION_DAYS to match the actual backup policy")
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", os.getenv("CAREER_CAPTCHA_SITE_KEY", "")):
        raise ValueError("Public production requires CAREER_CAPTCHA_SITE_KEY")
    for name in ("CAREER_CAPTCHA_ENABLED_CONFIRMED", "CAREER_SMTP_CONFIGURED_CONFIRMED",
                 "CAREER_EMAIL_CONFIRMATION_CONFIRMED"):
        if os.getenv(name) != "1":
            raise ValueError(f"Public production requires {name}=1 after provider setup verification")
    # Used exclusively server-side by account deletion. Never part of public configuration.
    account_admin_key()


def public_service_configuration() -> dict[str, Any]:
    from career.provider_config import provider_settings

    mode = access_mode()
    from career.access_config import source_repository_url
    from career.guest_access import LIFETIME, enabled
    return {
        "access_mode": mode,
        "guest_enabled": enabled(),
        "guest_session_seconds": LIFETIME if enabled() else None,
        "support_url": (source_repository_url() or "") + "/issues" if enabled() and source_repository_url() else "",
        "registration_open": registration_open(),
        "service_name": os.getenv("CAREER_SERVICE_NAME", "Career Harness").strip()[:100] or "Career Harness",
        "policy_version": policy_version(),
        "operator_name": os.getenv("CAREER_OPERATOR_NAME", "").strip()[:200],
        "support_email": os.getenv("CAREER_SUPPORT_EMAIL", "").strip()[:254],
        "privacy_url": "/privacy", "terms_url": "/terms",
        "captcha_site_key": os.getenv("CAREER_CAPTCHA_SITE_KEY", "").strip()[:200] if mode == "public" else "",
        "public_limits": public_limits(),
        "retention_days": None,
        "backup_retention_days": backup_retention_days(),
        "ai_provider": provider_settings().provider,
    }


def verify_confirmed_email(user: str, authorization: str | None,
                           transport: httpx.BaseTransport | None = None) -> None:
    """The fixed project's Auth API is authoritative; JWT user_metadata cannot confirm email."""
    try:
        config = authentication_configuration()
        public_config = public_auth_configuration()
    except ValueError:
        raise HTTPException(503, "로그인 설정을 확인해 주세요.") from None
    if config.mode != "supabase" or not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, AUTH_ERROR)
    try:
        with httpx.Client(timeout=5.0, follow_redirects=False, transport=transport) as client:
            with client.stream("GET", config.issuer + "/user", headers={
                "apikey": public_config["publishable_key"], "Authorization": authorization,
            }) as response:
                if response.status_code in {401, 403}:
                    raise HTTPException(401, AUTH_ERROR)
                if response.status_code != 200:
                    raise ValueError("Auth user lookup failed")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 65536:
                        raise ValueError("Oversized Auth user")
                payload = json.loads(body)
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(503, "계정 확인 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.") from None
    try:
        confirmed = payload.get("email_confirmed_at")
        email = payload.get("email")
        if (str(UUID(payload["id"])) != user or payload.get("is_anonymous") is not False
                or not isinstance(email, str) or not email.strip()
                or not isinstance(confirmed, str) or not confirmed):
            raise ValueError()
        datetime.fromisoformat(confirmed.replace("Z", "+00:00"))
    except (AttributeError, KeyError, TypeError, ValueError):
        raise HTTPException(403, "이메일 인증을 완료한 계정으로 로그인해 주세요.") from None


def ensure_public_member(db: Session, user: str, authorization: str | None) -> None:
    from career.db import Record, now
    from career.models import ServiceMember
    from career.service_access import SHARED_BUDGET_USER, require_member

    if access_mode() != "public":
        return
    if user.startswith("__career_"):
        raise HTTPException(403, "예약된 계정은 로그인할 수 없습니다.")
    member = db.get(ServiceMember, user, populate_existing=True)
    if member is not None:
        require_member(db, user)
        return
    if not registration_open():
        raise HTTPException(403, "현재 신규 가입을 받고 있지 않습니다. 기존 계정으로 로그인해 주세요.")
    from career.guest_access import enabled

    if enabled():
        # Membership can only originate in the server's bounded guest minting
        # endpoint. A signed but unregistered visitor cannot self-admit here.
        raise HTTPException(401, "체험 연결이 종료되었습니다. 새 작업실로 시작해 주세요.")
    verify_confirmed_email(user, authorization)
    from career.usage_limits import _settings

    _settings(db, SHARED_BUDGET_USER, lock=True)
    member = db.get(ServiceMember, user, populate_existing=True)
    if member is not None:
        require_member(db, user)
        return
    db.add(ServiceMember(user_id=user, status="ACTIVE", limits=public_limits(), updated_at=now()))
    db.add(Record(user_id=user, kind="PublicServiceJoined",
                  data={"method": "supabase_confirmed_email", "policy_version": policy_version()}))
    db.flush()


def onboarding_status(db: Session, user: str) -> dict[str, Any]:
    from career.db import Record

    current = policy_version()
    row = db.scalar(select(Record).where(Record.user_id == user, Record.kind == POLICY_RECORD_KIND)
                    .order_by(Record.created_at.desc(), Record.id.desc()).limit(1))
    accepted = row.data.get("policy_version") if row else None
    return {"required": access_mode() == "public" and accepted != current,
            "current_version": current, "accepted_version": accepted}


def require_public_consent(db: Session, user: str) -> None:
    if access_mode() == "public" and onboarding_status(db, user)["required"]:
        raise HTTPException(403, {"code": "POLICY_ACCEPTANCE_REQUIRED",
                                  "message": "이용약관과 개인정보 처리 안내를 확인해 주세요."})


def accept_policy(db: Session, user: str, version: str) -> dict[str, Any]:
    from career.db import Record, now
    from career.service_access import SHARED_BUDGET_USER, require_member

    if version != policy_version():
        raise HTTPException(409, "안내 내용이 변경되었습니다. 최신 내용을 확인한 뒤 다시 동의해 주세요.")
    from career.usage_limits import _settings

    _settings(db, SHARED_BUDGET_USER, lock=True)
    require_member(db, user)
    status = onboarding_status(db, user)
    if status["accepted_version"] != version:
        db.add(Record(user_id=user, kind=POLICY_RECORD_KIND,
                      data={"policy_version": version, "accepted": True, "accepted_at": now().isoformat()}))
        db.flush()
    return {**onboarding_status(db, user), "accepted": True}
