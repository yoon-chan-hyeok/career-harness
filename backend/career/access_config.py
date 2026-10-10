"""Access mode validation without importing a database or local settings."""

import os

import jwt


def access_mode() -> str:
    mode = os.getenv("CAREER_ACCESS_MODE", "invite").strip().lower()
    if mode not in {"invite", "public"}:
        raise ValueError("CAREER_ACCESS_MODE must be invite or public")
    return mode


def account_admin_key() -> tuple[str, bool]:
    """Validate the same server-only deletion credential at startup and at use."""
    modern = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    legacy = not bool(modern)
    key = modern or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    try:
        if not key or len(key) > 16384 or any(char.isspace() for char in key):
            raise ValueError()
        if legacy:
            if jwt.decode(key, options={"verify_signature": False}).get("role") != "service_role":
                raise ValueError()
        elif not key.startswith("sb_secret_") or key == "sb_secret_":
            raise ValueError()
    except (ValueError, jwt.PyJWTError, TypeError, AttributeError):
        raise ValueError("A valid server-only Supabase deletion key is required in its matching environment setting") from None
    return key, legacy
