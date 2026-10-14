"""Server-side identity verification. Imported document text never configures authentication."""

import hmac
import json
import os
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import jwt
from fastapi import HTTPException

ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "RS256"})
AUTH_ERROR = "로그인이 만료되었거나 유효하지 않습니다. 다시 로그인해 주세요."


def is_production() -> bool:
    return os.getenv("CAREER_ENV", "development").lower() in {"production", "staging"}


@dataclass(frozen=True)
class AuthConfiguration:
    mode: str
    issuer: str = ""
    audience: str = "authenticated"
    algorithms: tuple[str, ...] = ("ES256", "RS256")
    allowed_subjects: tuple[str, ...] = ()
    require_nonanonymous: bool = False

    @property
    def jwks_url(self) -> str:
        return self.issuer + "/.well-known/jwks.json"


def authentication_configuration() -> AuthConfiguration:
    from career.access_config import access_mode

    public = access_mode() == "public"
    mode = os.getenv("AUTH_MODE", "local").strip().lower()
    if mode not in {"local", "supabase", "guest"}:
        raise ValueError("AUTH_MODE must be local, supabase or guest")
    if mode == "guest":
        from career.guest_access import AUDIENCE, ISSUER, signing_key

        if not public or os.getenv("AUTH_TOKENS", "").strip() not in {"", "{}"}:
            raise ValueError("Guest trial requires public access and forbids local AUTH_TOKENS")
        if os.getenv("CAREER_ALLOWED_USER_IDS", "").strip() or os.getenv("CAREER_ADMIN_USER_IDS", "").strip():
            raise ValueError("Guest trial forbids bootstrap or administrator allowlists")
        signing_key()
        return AuthConfiguration(mode, ISSUER, AUDIENCE, ("HS256",))
    if is_production() and (mode != "supabase" or os.getenv("AUTH_TOKENS", "").strip() not in {"", "{}"}):
        raise ValueError("Production requires Supabase Auth and forbids local AUTH_TOKENS")
    if public and mode != "supabase":
        raise ValueError("Public access requires Supabase Auth")
    if mode == "local":
        return AuthConfiguration(mode=mode)
    origin = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("SUPABASE_URL must be an HTTPS project origin")
    issuer = os.getenv("SUPABASE_JWT_ISSUER", origin + "/auth/v1").strip().rstrip("/")
    if issuer != origin + "/auth/v1":
        raise ValueError("SUPABASE_JWT_ISSUER must match the configured project Auth endpoint")
    algorithms = tuple(x.strip() for x in os.getenv("SUPABASE_JWT_ALGORITHMS", "ES256,RS256").split(","))
    if not algorithms or not set(algorithms) <= ASYMMETRIC_ALGORITHMS:
        raise ValueError("Only asymmetric ES256/RS256 Supabase signing keys are supported")
    audience = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated").strip()
    if not audience:
        raise ValueError("SUPABASE_JWT_AUDIENCE is required")
    subjects = tuple(x.strip() for x in os.getenv("CAREER_ALLOWED_USER_IDS", "").split(",") if x.strip())
    for subject in subjects:
        UUID(subject)
    return AuthConfiguration(mode, issuer, audience, algorithms, subjects, public)


class SupabaseVerifier:
    """Bounded public-key cache with no token-controlled URLs or shared-secret fallback."""

    def __init__(self, config: AuthConfiguration, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.transport = transport
        self._keys: dict[str, jwt.PyJWK] = {}
        self._expires = 0.0
        self._last_refresh = float("-inf")
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        # Never send bearer credentials to JWKS, never follow redirects.
        try:
            with httpx.Client(timeout=5.0, follow_redirects=False, transport=self.transport) as client:
                response = client.get(self.config.jwks_url)
                response.raise_for_status()
                if len(response.content) > 1_048_576:
                    raise ValueError("Oversized JWKS")
                payload = response.json()
            candidates = payload.get("keys", [])
            if not isinstance(candidates, list) or len(candidates) > 32:
                raise ValueError("Invalid JWKS")
            keys: dict[str, jwt.PyJWK] = {}
            for raw in candidates:
                if not isinstance(raw, dict) or raw.get("alg") not in self.config.algorithms:
                    continue
                if raw.get("use", "sig") != "sig" or "d" in raw or raw.get("kty") not in {"RSA", "EC"}:
                    continue
                kid = raw.get("kid")
                if not isinstance(kid, str) or not kid or len(kid) > 256 or kid in keys:
                    raise ValueError("Invalid signing key identifier")
                keys[kid] = jwt.PyJWK.from_dict(raw)
            if not keys:
                raise ValueError("No supported asymmetric signing keys")
        except (httpx.HTTPError, ValueError, jwt.PyJWTError, TypeError, AttributeError):
            raise HTTPException(
                503, "로그인 검증 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."
            ) from None
        self._keys = keys
        self._expires = time.monotonic() + 600

    def verify(self, token: str) -> str:
        return str(self.verify_claims(token)["sub"])

    def verify_claims(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
            kid, algorithm = header.get("kid"), header.get("alg")
            if (
                algorithm not in self.config.algorithms
                or not isinstance(kid, str)
                or not kid
                or len(kid) > 256
                or header.get("crit")
            ):
                raise jwt.InvalidTokenError()
            with self._lock:
                now = time.monotonic()
                # Unknown ids can trigger one refresh per 30 seconds, rather than a fetch per attacker token.
                if now >= self._expires and now - self._last_refresh < 3:
                    raise HTTPException(
                        503, "로그인 검증 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."
                    )
                if now >= self._expires or (kid not in self._keys and now - self._last_refresh >= 30):
                    self._last_refresh = now
                    self._refresh()
                key = self._keys.get(kid)
            if key is None or key.algorithm_name != algorithm:
                raise jwt.InvalidTokenError()
            claims: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=list(self.config.algorithms),
                issuer=self.config.issuer,
                audience=self.config.audience,
                leeway=10,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "role"]},
            )
            subject = str(UUID(claims["sub"]))
            if claims["role"] != "authenticated" or claims.get("is_anonymous") is True:
                raise jwt.InvalidTokenError()
            if self.config.require_nonanonymous and claims.get("is_anonymous") is not False:
                raise jwt.InvalidTokenError()
            if self.config.allowed_subjects and subject not in self.config.allowed_subjects:
                raise HTTPException(403, "이 서비스 이용 권한이 없습니다.")
            return {**claims, "sub": subject}
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise HTTPException(401, AUTH_ERROR, headers={"WWW-Authenticate": "Bearer"}) from None


@lru_cache(maxsize=8)
def configured_verifier(config: AuthConfiguration) -> SupabaseVerifier:
    return SupabaseVerifier(config)


def public_auth_configuration() -> dict[str, str]:
    """Only intentionally public project configuration; secret/service-role keys are rejected."""
    config = authentication_configuration()
    result = {"provider": config.mode}
    if config.mode in {"local", "guest"}:
        return result
    public_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")
    if not public_key:
        raise ValueError("SUPABASE_PUBLISHABLE_KEY is required for browser login")
    if not public_key.startswith("sb_publishable_"):
        try:
            if jwt.decode(public_key, options={"verify_signature": False}).get("role") != "anon":
                raise ValueError()
        except (jwt.PyJWTError, ValueError):
            raise ValueError("Only a publishable or legacy anon key may be sent to the browser") from None
    result.update({"supabase_url": config.issuer.removesuffix("/auth/v1"), "publishable_key": public_key})
    return result


def authenticate(authorization: str | None) -> str:
    try:
        config = authentication_configuration()
    except ValueError:
        raise HTTPException(503, "로그인 설정을 확인해 주세요.") from None
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, AUTH_ERROR, headers={"WWW-Authenticate": "Bearer"})
    token = authorization[7:]
    if not token or len(token) > 16384 or any(c.isspace() for c in token):
        raise HTTPException(401, AUTH_ERROR)
    if config.mode == "guest":
        from career.guest_access import decode

        return str(decode(token)["sub"])
    if config.mode == "supabase":
        from dataclasses import replace

        from career.service_access import shared_service

        if shared_service():
            # Identity validation stays here; dynamic invite/revocation checks run in API dependency.
            config = replace(config, allowed_subjects=())
        return configured_verifier(config).verify(token)
    try:
        tokens = json.loads(os.getenv("AUTH_TOKENS", "{}"))
        if not isinstance(tokens, dict):
            raise ValueError()
        for expected, subject in tokens.items():
            if isinstance(expected, str) and hmac.compare_digest(token.encode(), expected.encode()):
                if not isinstance(subject, str) or not subject or len(subject) > 64:
                    raise ValueError()
                return subject
    except (ValueError, TypeError):
        raise HTTPException(503, "로그인 설정을 확인해 주세요.") from None
    raise HTTPException(401, AUTH_ERROR, headers={"WWW-Authenticate": "Bearer"})


def require_recent_otp(authorization: str | None, user: str, max_age_seconds: int = 300) -> None:
    """Destructive account actions require a signed fresh OTP AMR, never a fresh token iat."""
    from dataclasses import replace

    try:
        config = authentication_configuration()
    except ValueError:
        raise HTTPException(503, "로그인 설정을 확인해 주세요.") from None
    if config.mode != "supabase" or not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "이메일 인증 코드를 다시 확인한 뒤 진행해 주세요.")
    token = authorization[7:]
    if not token or len(token) > 16384 or any(c.isspace() for c in token):
        raise HTTPException(401, AUTH_ERROR)
    claims = configured_verifier(replace(config, allowed_subjects=())).verify_claims(token)
    if claims["sub"] != user:
        raise HTTPException(401, AUTH_ERROR)
    instant = time.time()
    amr = claims.get("amr", [])
    if not isinstance(amr, list) or not any(
        isinstance(item, dict) and item.get("method") == "otp"
        and isinstance(item.get("timestamp"), (int, float)) and not isinstance(item["timestamp"], bool)
        and instant - max_age_seconds <= item["timestamp"] <= instant + 10
        for item in amr
    ):
        raise HTTPException(401, "이메일 인증 코드를 다시 확인한 뒤 5분 안에 진행해 주세요.")
    from career.public_service import verify_confirmed_email

    verify_confirmed_email(user, authorization)
