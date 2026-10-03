"""Deployment validation, redacted readiness, and bounded request handling."""

import hashlib
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from career.authentication import authentication_configuration, is_production, public_auth_configuration
from career.provider_config import provider_available, provider_settings, provider_status


def integer_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        if not minimum <= value <= maximum:
            raise ValueError()
        return value
    except ValueError:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}") from None


def validate_runtime_settings() -> None:
    """Fail before accepting traffic; messages name settings, never disclose their values."""
    if os.getenv("CAREER_ENV", "development").lower() not in {"development", "test", "production", "staging"}:
        raise ValueError("CAREER_ENV must be development, test, staging, or production")
    authentication_configuration()
    if provider_settings().model:
        from career.provider_policy import validate_provider_configuration

        validate_provider_configuration(provider_settings().model)
    if not is_production():
        return
    public_auth_configuration()
    try:
        database = make_url(os.getenv("DATABASE_URL", ""))
        if database.get_backend_name() != "postgresql":
            raise ValueError()
        if database.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
            raise ValueError()
    except Exception:
        # SQLAlchemy parse failures may include the URL; do not forward them.
        raise ValueError("Production DATABASE_URL requires PostgreSQL and TLS sslmode") from None
    hosts = [x.strip() for x in os.getenv("CAREER_ALLOWED_HOSTS", "").split(",") if x.strip()]
    if not hosts or "*" in hosts:
        raise ValueError("CAREER_ALLOWED_HOSTS must list explicit backend hosts")
    for origin in os.getenv("CAREER_CORS_ORIGINS", "").split(","):
        if origin.strip():
            parsed = urlsplit(origin.strip())
            if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
                raise ValueError("Production CAREER_CORS_ORIGINS must be exact HTTPS origins")
    if os.getenv("JEV_SHADOW_ENABLED", "0") == "1" and not os.getenv("JEV_API_KEY"):
        raise ValueError("JEV_SHADOW_ENABLED requires JEV_API_KEY")
    if os.getenv("CAREER_REQUIRE_AI", "0") == "1" and not provider_available():
        raise ValueError("CAREER_REQUIRE_AI requires a configured AI provider and its credentials")
    integer_setting("CAREER_MAX_REQUEST_BYTES", 10_485_760, 1024, 104_857_600)
    integer_setting("CAREER_RATE_LIMIT_PER_MINUTE", 120, 1, 10000)


def migration_heads() -> set[str]:
    project = Path(__file__).resolve().parents[2]
    config = Config(str(project / "alembic.ini"))
    config.set_main_option("script_location", str(project / "migrations"))
    return set(ScriptDirectory.from_config(config).get_heads())


def readiness(engine: Engine) -> tuple[int, dict[str, Any]]:
    """Read-only checks. Configuration is distinguished from a live provider call."""
    checks: dict[str, Any] = {}
    ready = True
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            checks["database"] = "ok"
            current = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
            checks["migrations"] = "ok" if current == migration_heads() else "pending"
            ready = checks["migrations"] == "ok"
            if engine.dialect.name == "postgresql":
                vector = connection.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname='vector'")
                ).scalar()
                embeddings = connection.execute(
                    text("SELECT to_regclass('public.evidence_embeddings')")
                ).scalar()
                checks["retrieval"] = "ok" if vector and embeddings else "unavailable"
                ready = ready and checks["retrieval"] == "ok"
                if is_production():
                    from career.db import Base

                    names = list(Base.metadata.tables) + ["evidence_embeddings", "alembic_version"]
                    protections = connection.execute(
                        text(
                            "SELECT c.relname, c.relrowsecurity FROM pg_class c "
                            "JOIN pg_namespace n ON n.oid=c.relnamespace "
                            "WHERE n.nspname='public' AND c.relname = ANY(:names)"
                        ),
                        {"names": names},
                    ).all()
                    private_rows = {name: enabled for name, enabled in protections}
                    protected = set(names) <= set(private_rows) and all(private_rows.values())
                    roles = (
                        connection.execute(
                            text("SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated')")
                        )
                        .scalars()
                        .all()
                    )
                    for role in roles:
                        leaked = connection.execute(
                            text(
                                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                                "WHERE n.nspname='public' AND c.relname = ANY(:names) "
                                "AND has_table_privilege(:role, c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')"
                            ),
                            {"names": names, "role": role},
                        ).scalar()
                        protected = protected and not leaked
                    checks["data_api_privacy"] = "ok" if protected else "unprotected"
                    ready = ready and protected
            else:
                checks["retrieval"] = "lexical_only"
    except Exception:
        checks.setdefault("database", "unavailable")
        checks.setdefault("migrations", "unavailable")
        ready = False
    try:
        validate_runtime_settings()
        checks["authentication"] = "configured"
    except Exception:
        checks["authentication"] = "misconfigured"
        ready = False
    ai_status = provider_status()
    checks["llm"] = {
        "status": "configured" if ai_status["configured"] else "manual_only",
        "provider": ai_status["provider"],
        "live_verified": ai_status["live_verified"],
        "verified_at": ai_status["verified_at"],
    }
    shadow = os.getenv("JEV_SHADOW_ENABLED", "0") == "1"
    checks["jev"] = {
        "status": "configured" if shadow and os.getenv("JEV_API_KEY") else "disabled",
        "mode": "shadow_only",
        "live_verified": False,
    }
    return (200 if ready else 503), {"status": "ready" if ready else "not_ready", "checks": checks}


class RequestProtection:
    """Single-process guard; an ingress limit is additionally required for multiple replicas."""

    def __init__(self, app: ASGIApp, max_bytes: int, per_minute: int):
        self.app, self.max_bytes, self.per_minute = app, max_bytes, per_minute
        self.buckets: OrderedDict[str, tuple[float, int]] = OrderedDict()

    def _allow(self, identity: str) -> bool:
        now = time.monotonic()
        start, count = self.buckets.get(identity, (now, 0))
        if now - start >= 60:
            start, count = now, 0
        self.buckets[identity] = (start, count + 1)
        self.buckets.move_to_end(identity)
        if len(self.buckets) > 10000:
            self.buckets.popitem(last=False)
        return count < self.per_minute

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        headers = dict(scope.get("headers", []))
        if path.startswith("/api/"):
            ip = str(scope.get("client", ("unknown",))[0])
            token_hash = hashlib.sha256(headers.get(b"authorization", b"")).hexdigest()
            if not self._allow("ip:" + ip) or not self._allow("token:" + token_hash):
                await JSONResponse(
                    content={"detail": "요청이 많습니다. 잠시 후 다시 시도해 주세요."},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )(scope, receive, send)
                return
        if scope.get("method") in {"POST", "PUT", "PATCH", "DELETE"}:
            try:
                declared = int(headers.get(b"content-length", b"0"))
            except ValueError:
                declared = self.max_bytes + 1
            if declared < 0 or declared > self.max_bytes:
                await JSONResponse(
                    content={"detail": "입력 자료가 허용 크기를 초과했습니다."}, status_code=413
                )(scope, receive, send)
                return
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > self.max_bytes:
                    await JSONResponse(
                        content={"detail": "입력 자료가 허용 크기를 초과했습니다."}, status_code=413
                    )(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            replayed = False

            async def replay() -> Message:
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            inner_receive = replay
        else:
            inner_receive = receive

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"cache-control", b"no-store"),
                    ]
                )
                if is_production():
                    response_headers.append((b"strict-transport-security", b"max-age=31536000"))
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, inner_receive, secure_send)


def install_security(app: FastAPI) -> None:
    app.add_middleware(
        RequestProtection,
        max_bytes=integer_setting("CAREER_MAX_REQUEST_BYTES", 10_485_760, 1024, 104_857_600),
        per_minute=integer_setting(
            "CAREER_RATE_LIMIT_PER_MINUTE", 120 if is_production() else 10000, 1, 10000
        ),
    )
    hosts = [x.strip() for x in os.getenv("CAREER_ALLOWED_HOSTS", "").split(",") if x.strip()]
    if hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    origins = [x.strip().rstrip("/") for x in os.getenv("CAREER_CORS_ORIGINS", "").split(",") if x.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )
