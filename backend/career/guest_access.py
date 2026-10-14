"""Bounded visitor identities for the explicitly enabled public trial.

Each browser gets a distinct signed session and DB membership. There is no
shared owner token, email claim, Supabase credential or administrator privilege.
"""
import hashlib
import hmac
import ipaddress
import os
import secrets
import time
from datetime import timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

ISSUER = "career-harness:guest"
AUDIENCE = "career-harness:guest-workspace"
SESSION_KIND = "GuestSession"
LIFETIME = 86400


def enabled() -> bool:
    return os.getenv("AUTH_MODE", "local").strip().lower() == "guest"


def signing_key() -> str:
    key = os.getenv("CAREER_GUEST_SESSION_SECRET", "")
    if len(key) < 64 or len(key) > 512 or any(char.isspace() for char in key):
        raise ValueError("Guest sessions require a private random CAREER_GUEST_SESSION_SECRET of at least 64 characters")
    return key


def decode(token: str) -> dict:
    try:
        claims = jwt.decode(token, signing_key(), algorithms=["HS256"], issuer=ISSUER, audience=AUDIENCE,
                            options={"require": ["sub", "iat", "exp", "jti", "guest"]})
        if (str(UUID(claims["sub"])) != claims["sub"] or claims["guest"] is not True
                or not isinstance(claims["jti"], str) or len(claims["jti"]) != 64
                or type(claims["iat"]) is not int or type(claims["exp"]) is not int
                or claims["exp"] - claims["iat"] != LIFETIME):
            raise ValueError()
        return claims
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise HTTPException(401, "체험 연결이 만료되었거나 유효하지 않습니다. 새 작업실로 시작해 주세요.") from None


def verify_session(db: Session, user: str, authorization: str | None) -> None:
    from career.db import Record

    if not enabled():
        return
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    claims = decode(token)
    row = db.scalar(select(Record).where(Record.user_id == user, Record.kind == SESSION_KIND))
    if (claims["sub"] != user or row is None
            or not hmac.compare_digest(row.data.get("jti_hash", ""), hashlib.sha256(claims["jti"].encode()).hexdigest())
            or row.data.get("expires_at") != claims["exp"]):
        raise HTTPException(401, "체험 연결이 종료되었습니다. 새 작업실로 시작해 주세요.")


def _network_identity(request: Request) -> str:
    # Vercel overwrites this header; arbitrary forwarded headers are never used
    # outside its runtime. Never store raw IP addresses in the database.
    address = request.headers.get("x-vercel-forwarded-for", "") if os.getenv("VERCEL") == "1" else ""
    address = address.split(",", 1)[0].strip() or (request.client.host if request.client else "unknown")
    try:
        address = str(ipaddress.ip_address(address))
    except ValueError:
        address = "unknown"
    return hmac.new(signing_key().encode(), address.encode(), hashlib.sha256).hexdigest()


def _admission(db: Session, identity: str, maximum: int, day: int) -> None:
    from career.models import RequestRateBucket

    bucket = db.get(RequestRateBucket, identity)
    if bucket is None:
        db.add(RequestRateBucket(user_id=identity, minute=day, requests=1, mutations=0))
    elif bucket.minute != day:
        bucket.minute, bucket.requests = day, 1
    elif bucket.requests >= maximum:
        raise HTTPException(429, "오늘의 체험 시작 한도에 도달했습니다. 저장된 연결을 사용하거나 내일 다시 방문해 주세요.")
    else:
        bucket.requests += 1


def create_session(db: Session, request: Request) -> dict:
    from career.access_config import access_mode
    from career.db import Record, now
    from career.models import ServiceMember
    from career.public_service import public_limits, registration_open
    from career.service_access import SHARED_BUDGET_USER
    from career.usage_limits import _settings

    if not enabled() or access_mode() != "public" or not registration_open():
        raise HTTPException(403, "현재 게스트 체험을 받고 있지 않습니다.")
    key = signing_key()
    # Serialize admissions under the same global lock as usage and membership.
    # Limits cannot be changed by visitors or replenished by deleting a session.
    _settings(db, SHARED_BUDGET_USER, lock=True)
    day = int(time.time() // 86400)
    _admission(db, "__career_guest_global__", 100, day)
    _admission(db, "__career_guest_network_" + _network_identity(request)[:40], 20, day)
    instant = int(time.time())
    user, nonce = str(uuid4()), secrets.token_hex(32)
    expires = instant + LIFETIME
    db.add(ServiceMember(user_id=user, status="ACTIVE", limits=public_limits(), updated_at=now()))
    db.add(Record(user_id=user, kind=SESSION_KIND,
                  data={"jti_hash": hashlib.sha256(nonce.encode()).hexdigest(), "expires_at": expires}))
    token = jwt.encode({"sub": user, "iat": instant, "exp": expires, "jti": nonce, "guest": True,
                        "iss": ISSUER, "aud": AUDIENCE}, key, algorithm="HS256")
    return {"access_token": token, "expires_in": LIFETIME, "token_type": "bearer"}


def delete_guest(db: Session, user: str) -> dict:
    from career.account_lifecycle import (
        _close_access,
        _ensure_independent,
        _mark_complete,
        _purge_career_data,
    )

    _ensure_independent(db)
    _close_access(db, user)
    _purge_career_data(db, user)
    _mark_complete(db, user)
    return {"status": "DELETED", "access_closed": True, "career_data_deleted": True,
            "auth_account_deleted": True, "retry_allowed": False}


def cleanup_expired(bind, limit: int = 5) -> int:
    """Bounded cleanup during new visits; never claims an exact timed purge."""
    from career.db import Record, now

    with Session(bind) as scan:
        users = list(scan.scalars(select(Record.user_id).where(
            Record.kind == SESSION_KIND, Record.created_at <= now() - timedelta(seconds=LIFETIME)
        ).order_by(Record.created_at).limit(limit)))
    for user in users:
        with Session(bind) as lifecycle:
            delete_guest(lifecycle, user)
    return len(users)
