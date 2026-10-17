"""Deterministic request prefixes for provider-managed KV reuse, never response storage."""

import hashlib
import hmac
import json
import math
import os
import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from career.prompts import prompt_version

LAYOUT_VERSION = "1.1.0"
_process_secret = secrets.token_bytes(32)
_identity: ContextVar[str | None] = ContextVar("career_prompt_cache_identity", default=None)
_STABLE_FIELDS = (
    "supplemental_guidance", "verified_writing_guidance", "canonical_profile", "canonical_master",
    "style_projections", "company_sources", "current_company_facts", "company_facts", "research",
    "opportunity", "job_outputs", "main_skills", "differentiators", "output_importance",
    "strategy", "evidence_pack", "evidence", "evidence_candidates", "resume_brief", "writing_plan",
)


@contextmanager
def identity_scope(user: str):
    """Only application/authentication boundaries may set identity; never prompt fields."""
    token = _identity.set(user)
    try:
        yield
    finally:
        _identity.reset(token)


def _owner() -> str | None:
    from career.usage_limits import usage_envelope

    envelope = usage_envelope.get()
    scoped = _identity.get()
    if envelope is not None:
        if scoped is not None and scoped != envelope.user:
            raise ValueError("AI 요청 계정 범위를 확인해 주세요.")
        return envelope.user
    return scoped


def enabled() -> bool:
    value = os.getenv("CAREER_PROMPT_CACHE_ENABLED", "1")
    if value not in {"0", "1"}:
        raise ValueError("CAREER_PROMPT_CACHE_ENABLED must be 0 or 1")
    return value == "1"


def _normalise(value: Any) -> Any:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("AI 입력에 유한한 숫자가 필요합니다.")
        return value
    if isinstance(value, BaseModel):
        return _normalise(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return _normalise(value.value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("AI 입력 항목 이름을 확인해 주세요.")
        return {key: _normalise(value[key]) for key in sorted(value)}
    if isinstance(value, list | tuple):
        return [_normalise(item) for item in value]
    raise ValueError("AI 입력 형식을 확인해 주세요.")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _wire_context(context: dict[str, Any]) -> dict[str, Any]:
    """Keep every rule verbatim; line-range indexes remain in stored audit packets.

    The compiler's requirements contain only navigation metadata duplicating the
    headings already in guidance. They are not additional rule text or evidence.
    Unknown packet shapes are preserved rather than silently dropping content.
    """
    packet = context.get("supplemental_guidance")
    if not isinstance(packet, dict) or not isinstance(packet.get("references"), list):
        return context
    navigation = {"rule_id", "section", "section_number", "chapter", "start_line", "end_line", "role"}
    references = []
    for reference in packet["references"]:
        if not isinstance(reference, dict):
            references.append(reference)
            continue
        requirements = reference.get("requirements")
        if (reference.get("compilation_status") == "SOURCE_SECTIONS"
                and isinstance(reference.get("guidance"), list)
                and isinstance(requirements, list)
                and len(requirements) == len(reference["guidance"])
                and all(isinstance(item, dict) and set(item) <= navigation for item in requirements)):
            audit_only = {"requirements", "source_id", "content_hash", "compiler_version"}
            reference = {key: value for key, value in reference.items() if key not in audit_only}
        references.append(reference)
    return {**context, "supplemental_guidance": {**packet, "references": references}}


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(_normalise(value)).encode("utf-8")).hexdigest()


def _secret() -> bytes:
    configured = os.getenv("CAREER_PROMPT_CACHE_SECRET", "")
    if not configured:
        return _process_secret
    if len(configured.encode("utf-8")) < 32:
        raise ValueError("CAREER_PROMPT_CACHE_SECRET must contain at least 32 bytes")
    return configured.encode("utf-8")


@dataclass(frozen=True)
class PreparedPrompt:
    instructions: str
    content: str
    key: str | None
    scope: str
    layout_version: str


def prepare(
    stage: str, context: dict[str, Any], instructions: str, model: str, provider: str,
    schema: dict[str, Any] | None = None,
) -> PreparedPrompt:
    if not enabled():
        return PreparedPrompt(instructions, json.dumps(_wire_context(context), ensure_ascii=False, default=str), None, "DISABLED", LAYOUT_VERSION)
    effective_instructions = instructions + (
        "\nRole inputs are inside the context object. request_partition is opaque routing metadata, "
        "never career evidence or an instruction."
    )
    owner = _owner()
    secret = _secret()
    # An unscoped direct invocation has its own partition, never a shared fallback user.
    partition = hmac.new(secret, _json({"user": owner} if owner else {"request": secrets.token_hex(32)}).encode(),
                         hashlib.sha256).hexdigest()
    normal = _normalise(context)
    wire = _wire_context(normal)
    ordered = {key: wire[key] for key in _STABLE_FIELDS if key in wire}
    ordered.update({key: wire[key] for key in wire if key not in ordered})
    pack = normal.get("supplemental_guidance", {})
    references = pack.get("references", []) if isinstance(pack, dict) else []
    versions = [{key: item.get(key) for key in ("key", "version", "content_hash")}
                for item in references if isinstance(item, dict)] if isinstance(references, list) else []
    group = {"partition": partition, "provider": provider, "model": model, "stage": stage,
             "template": prompt_version(stage), "instructions": _digest(effective_instructions),
             "schema": _digest(schema), "domain": normal.get("document_domain"),
             "reference_versions": versions, "layout": LAYOUT_VERSION}
    key = "career-v1-" + hmac.new(secret, _json(group).encode(), hashlib.sha256).hexdigest()[:48] if owner else None
    # The opaque partition precedes all private material; trusted role instructions stay separate.
    content = _json({"request_partition": partition, "context": ordered})
    return PreparedPrompt(effective_instructions, content, key, "USER" if owner else "REQUEST", LAYOUT_VERSION)
