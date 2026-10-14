"""Prepare the dedicated serverless entrypoint without database writes or network calls."""

import os
import re
import ssl
import tempfile
from pathlib import Path

from sqlalchemy.engine import make_url

from career.production import integer_setting, validate_runtime_settings

_CA_DIRECTORIES: list[tempfile.TemporaryDirectory] = []
MAX_REQUEST_BYTES = 4_000_000


def _certificate_file(pem: str) -> Path:
    """Accept public certificates only; keep the trust file for this process's lifetime."""
    if len(pem) > 65_536 or not re.fullmatch(
        r"(?:-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----\s*)+",
        pem.strip(),
    ):
        raise ValueError("CAREER_DATABASE_CA_PEM must contain only public PEM certificates")
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=pem)
    except (ssl.SSLError, ValueError):
        raise ValueError("CAREER_DATABASE_CA_PEM is not a valid certificate bundle") from None
    directory = tempfile.TemporaryDirectory(prefix="career-database-ca-")
    path = Path(directory.name) / "database-ca.crt"
    try:
        with path.open("x", encoding="ascii", newline="\n") as handle:
            handle.write(pem)
        path.chmod(0o600)
    except OSError:
        directory.cleanup()
        raise ValueError("Database CA trust file could not be prepared") from None
    _CA_DIRECTORIES.append(directory)
    return path


def prepare_serverless_environment() -> None:
    """Fail closed before the API imports and creates its SQLAlchemy engine.

    This entrypoint is production/staging only. It does not load dotenv files,
    import a local DB, run migrations, read private provider profiles, or call AI.
    """
    if os.getenv("CAREER_ENV", "").lower() not in {"production", "staging"}:
        raise ValueError("Serverless CAREER_ENV must be production or staging")
    if os.getenv("RUN_MIGRATIONS", "0") != "0":
        raise ValueError("Serverless RUN_MIGRATIONS must be 0; use a separate release command")
    try:
        database = make_url(os.getenv("DATABASE_URL", ""))
        if database.get_backend_name() != "postgresql" or not database.host:
            raise ValueError()
        if database.query.get("sslmode") != "verify-full":
            raise ValueError()
    except Exception:
        raise ValueError("Serverless DATABASE_URL requires PostgreSQL and sslmode=verify-full") from None
    pem = os.getenv("CAREER_DATABASE_CA_PEM", "")
    if not pem:
        raise ValueError("CAREER_DATABASE_CA_PEM is required for the serverless database connection")
    os.environ.setdefault("DATABASE_POOL_MODE", "transaction")
    # Fluid Compute shares a Python instance across concurrent requests. Keep
    # one bounded connection available for visitor access while AI work holds
    # its business transaction; an explicit pool of one remains supported.
    os.environ.setdefault("DATABASE_POOL_SIZE", "2")
    os.environ.setdefault("DATABASE_MAX_OVERFLOW", "0")
    os.environ.setdefault("CAREER_MAX_REQUEST_BYTES", str(MAX_REQUEST_BYTES))
    os.environ.setdefault("EXECUTION_TIMEOUT_SECONDS", "330")
    if os.environ["DATABASE_POOL_MODE"] not in {"session", "transaction"}:
        raise ValueError("DATABASE_POOL_MODE must be session or transaction")
    integer_setting("DATABASE_POOL_SIZE", 2, 1, 2)
    integer_setting("DATABASE_MAX_OVERFLOW", 0, 0, 0)
    integer_setting("CAREER_MAX_REQUEST_BYTES", MAX_REQUEST_BYTES, 1024, MAX_REQUEST_BYTES)
    integer_setting("EXECUTION_TIMEOUT_SECONDS", 330, 330, 900)
    # Preserve the explicit host allowlist and add only the deployment's exact host.
    validate_runtime_settings()
    deployment_host = os.getenv("VERCEL_URL", "")
    if deployment_host:
        if not re.fullmatch(r"[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+", deployment_host):
            raise ValueError("VERCEL_URL must be a hostname without a scheme or path")
        hosts = [x.strip() for x in os.environ["CAREER_ALLOWED_HOSTS"].split(",") if x.strip()]
        if deployment_host not in hosts:
            os.environ["CAREER_ALLOWED_HOSTS"] = ",".join([*hosts, deployment_host])
    # This never changes the URL's host/password or relaxes its TLS verification.
    path = _certificate_file(pem)
    os.environ["DATABASE_URL"] = database.update_query_dict(
        {"sslrootcert": str(path)}
    ).render_as_string(hide_password=False)
    os.environ["CAREER_SERVERLESS_RUNTIME"] = "1"
