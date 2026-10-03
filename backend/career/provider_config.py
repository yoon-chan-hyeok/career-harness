"""Private local provider profiles and redacted configuration/verification status.

Only the authenticated local owner can change profiles. Server environment
selection and credentials take precedence, and production never loads local keys.
Reading configuration never performs an external request.
"""

import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / ".provider-settings.json"
LOCAL_SETTINGS_PATH = PROJECT_ROOT / ".local-settings.json"
MAX_SETTINGS_BYTES = 65536
DEFAULT_MODELS = {
    "huggingface": "openai/gpt-oss-120b:fireworks-ai",
    "groq": "openai/gpt-oss-120b",
}
ENV_FIELDS = {
    "huggingface": ("HF_TOKEN", "HF_MODEL", "HF_FREE_ONLY_CONFIRMED"),
    "groq": ("GROQ_API_KEY", "GROQ_MODEL", "GROQ_FREE_ONLY_CONFIRMED"),
    "openai": ("OPENAI_API_KEY", "OPENAI_MODEL", None),
}
_LOCK = threading.RLock()
_MEMORY_VERIFICATION: tuple[str, bool, str | None] | None = None
CONFIG_ERROR = "AI 제공자 설정을 확인해 주세요. 저장된 키는 응답에 표시하지 않습니다."


def _model(value: str) -> str:
    if value and not re.fullmatch(r"[A-Za-z0-9_./:-]{1,200}", value):
        raise ValueError(CONFIG_ERROR)
    if ".." in value or "://" in value:
        raise ValueError(CONFIG_ERROR)
    return value


def _token(value: str) -> str:
    if len(value) > 4096 or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError(CONFIG_ERROR)
    return value


class PrivateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProviderConfigRequest(PrivateSchema):
    provider: Literal["none", "huggingface", "groq"]
    model: str = Field(max_length=200)
    token: str | None = Field(default=None, repr=False, max_length=4096)
    free_only_confirmed: bool

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        return _model(value)

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: str | None) -> str | None:
        return _token(value) if value is not None else None


class ProviderCheckRequest(PrivateSchema):
    pass


class Profile(PrivateSchema):
    model: str = Field(max_length=200)
    token: str = Field(default="", repr=False, max_length=4096)
    free_only_confirmed: bool = False

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        return _model(value)

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: str) -> str:
        return _token(value)


class Verification(PrivateSchema):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    success: bool
    verified_at: str | None = None

    @field_validator("verified_at")
    @classmethod
    def validate_time(cls, value: str | None) -> str | None:
        if value is not None:
            if len(value) > 40 or datetime.fromisoformat(value).tzinfo is None:
                raise ValueError(CONFIG_ERROR)
        return value


class PrivateSettings(PrivateSchema):
    version: Literal[1] = 1
    selected_provider: Literal["none", "huggingface", "groq"] = "none"
    profiles: dict[Literal["huggingface", "groq"], Profile] = Field(default_factory=dict)
    verification: Verification | None = None


@dataclass(frozen=True)
class ProviderSettings:
    provider: str
    model: str
    token: str = field(repr=False)
    free_only_confirmed: bool
    credential_source: str


def _local_mode() -> bool:
    return (
        os.getenv("CAREER_ENV", "development").strip().lower() in {"development", "test"}
        and os.getenv("AUTH_MODE", "local").strip().lower() == "local"
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        if path.is_symlink() or not path.is_file():
            raise ValueError()
        with path.open("rb") as handle:
            raw = handle.read(MAX_SETTINGS_BYTES + 1)
        if len(raw) > MAX_SETTINGS_BYTES:
            raise ValueError()
        result = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (OSError, ValueError, UnicodeError):
        raise ValueError(CONFIG_ERROR) from None


def _private_settings() -> PrivateSettings:
    try:
        return PrivateSettings.model_validate(_read_json(SETTINGS_PATH))
    except (ValidationError, ValueError):
        raise ValueError(CONFIG_ERROR) from None


def _write_settings(settings: PrivateSettings) -> None:
    temporary: str | None = None
    try:
        if SETTINGS_PATH.is_symlink():
            raise ValueError()
        payload = json.dumps(settings.model_dump(), ensure_ascii=False, indent=2).encode("utf-8")
        if len(payload) > MAX_SETTINGS_BYTES:
            raise ValueError()
        descriptor, temporary = tempfile.mkstemp(
            prefix=SETTINGS_PATH.name + ".", suffix=".tmp", dir=SETTINGS_PATH.parent
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, SETTINGS_PATH)
    except (OSError, ValueError):
        raise ValueError(CONFIG_ERROR) from None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass


def _owner(user: str | None) -> bool:
    if not user or not _local_mode():
        return False
    try:
        owner = _read_json(LOCAL_SETTINGS_PATH).get("user")
        return isinstance(owner, str) and 1 <= len(owner) <= 64 and user == owner
    except ValueError:
        return False


def require_local_owner(user: str | None) -> None:
    if not _owner(user):
        raise HTTPException(403, "개인 로컬 환경의 소유자만 AI 연결 설정을 관리할 수 있습니다.")


def provider_settings() -> ProviderSettings:
    with _LOCK:
        explicit = os.getenv("CAREER_LLM_PROVIDER", "").strip().lower()
        if explicit and explicit not in {"none", "huggingface", "groq", "openai"}:
            raise ValueError(CONFIG_ERROR)
        private = _private_settings() if _local_mode() and not explicit else PrivateSettings()
        selected = explicit or (
            private.selected_provider if SETTINGS_PATH.exists() and _local_mode() else ""
        )
        if not selected:
            selected = "openai" if os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL") else "none"
        if selected == "none":
            return ProviderSettings("none", "", "", False, "missing")
        token_field, model_field, free_field = ENV_FIELDS[selected]
        profile = (
            private.profiles.get("huggingface" if selected == "huggingface" else "groq")
            if selected in {"huggingface", "groq"} else None
        )
        environment_token = os.getenv(token_field, "").strip()
        token = _token(environment_token or (profile.token if profile else ""))
        model = _model(os.getenv(model_field, "").strip() or (profile.model if profile else "")
                       or DEFAULT_MODELS.get(selected, ""))
        free = (
            os.getenv(free_field) == "1"
            if free_field is not None and free_field in os.environ
            else (profile.free_only_confirmed if profile else False)
        )
        source = "server_environment" if environment_token else "local_private_file" if token else "missing"
        return ProviderSettings(selected, model, token, free, source)


def provider_available() -> bool:
    try:
        settings = provider_settings()
        return bool(
            settings.provider != "none"
            and settings.token
            and settings.model
            and (settings.provider == "openai" or settings.free_only_confirmed)
        )
    except ValueError:
        return False


def _fingerprint(settings: ProviderSettings) -> str:
    value = [settings.provider, settings.model, settings.token, settings.free_only_confirmed]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode("utf-8")).hexdigest()


def _editable(user: str | None, settings: ProviderSettings) -> bool:
    return bool(
        _owner(user)
        and not os.getenv("CAREER_LLM_PROVIDER", "").strip()
        and settings.credential_source != "server_environment"
    )


def provider_status(user: str | None = None) -> dict[str, Any]:
    with _LOCK:
        settings = provider_settings()
        verification = _MEMORY_VERIFICATION
        if verification is None and _local_mode():
            try:
                saved = _private_settings().verification
                if saved is not None:
                    verification = (saved.fingerprint, saved.success, saved.verified_at)
            except ValueError:
                # An explicit environment selection must not depend on unrelated local metadata.
                verification = None
        live = bool(
            provider_available()
            and verification is not None
            and verification[0] == _fingerprint(settings)
            and verification[1]
        )
        return {
            "provider": settings.provider,
            "model": settings.model,
            "configured": provider_available(),
            "live_verified": live,
            "verified_at": verification[2] if live and verification is not None else None,
            "editable": _editable(user, settings),
            "credential_source": settings.credential_source,
            "free_only_confirmed": settings.free_only_confirmed,
            "token_configured": bool(settings.token),
        }


def configure_provider(user: str, request: ProviderConfigRequest) -> dict[str, Any]:
    global _MEMORY_VERIFICATION
    with _LOCK:
        require_local_owner(user)
        current = provider_settings()
        if not _editable(user, current):
            raise HTTPException(403, "서버 환경에 설정된 AI 연결은 서버 설정에서 변경해 주세요.")
        saved = _private_settings()
        if request.provider != "none":
            old = saved.profiles.get(request.provider)
            model = request.model or DEFAULT_MODELS[request.provider]
            saved.profiles[request.provider] = Profile(
                model=model,
                token=request.token or (old.token if old else ""),
                free_only_confirmed=request.free_only_confirmed,
            )
        saved.selected_provider = request.provider
        saved.verification = None
        _write_settings(saved)
        _MEMORY_VERIFICATION = None
        return provider_status(user)


def note_verification(success: bool, expected: ProviderSettings | None = None) -> None:
    """Accept a result only for the same provider/model/key/consent snapshot."""
    global _MEMORY_VERIFICATION
    with _LOCK:
        current = provider_settings()
        if expected is not None and _fingerprint(expected) != _fingerprint(current):
            return
        verified_at = datetime.now(timezone.utc).isoformat() if success else None
        verification = Verification(fingerprint=_fingerprint(current), success=success, verified_at=verified_at)
        # A failed probe must clear a previous live result even if disk persistence fails.
        _MEMORY_VERIFICATION = (verification.fingerprint, success, verified_at)
        if _local_mode():
            try:
                saved = _private_settings()
            except ValueError:
                if os.getenv("CAREER_LLM_PROVIDER", "").strip():
                    return
                raise
            saved.verification = verification
            _write_settings(saved)
