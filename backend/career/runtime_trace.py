"""Provider telemetry containing hashes and operational metadata, never prompt text."""

import hashlib
import json
import math
import re
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

TraceSink = Callable[[str, str, dict[str, Any]], None]
trace_sink: ContextVar[TraceSink | None] = ContextVar("career_trace_sink", default=None)
trace_context: ContextVar[dict[str, Any]] = ContextVar("career_trace_context", default={})

_CONTEXT_KEYS = {
    "execution_run_id",
    "workspace_id",
    "input_artifact_ids",
    "question_id",
    "prompt_version",
    "source_ids",
    "document_domain",
    "reference_pack",
    "reference_versions",
    "input_hash_only",
}
_DATA_KEYS = {
    "prompt_template_version",
    "model",
    "latency_ms",
    "usage",
    "cost",
    "retry_count",
    "input_hash",
    "output_hash",
    "status",
    "error_code",
    "operation",
    "mode",
    "task",
    "disagreement",
    "confidence",
    "primary_confidence",
    "shadow_confidence",
    "budget_status",
    "cost_basis",
    "timeout_seconds",
    "max_output_tokens",
    "max_input_tokens",
    "max_cost_usd",
    "tool_calls",
}


def _tag(value: Any) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value) else None


def input_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def numeric_metadata(value: Any) -> Any:
    """Usage and price metadata may contain numbers, not provider-returned prose."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {
            key: numeric_metadata(item)
            for key, item in value.items()
            if isinstance(key, str)
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key)
            and isinstance(item, int | float | dict)
        }
    return None


def numeric_confidence(value: Any) -> float | None:
    """Retain a probability only; prose, booleans and invalid ranges remain unknown."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    if isinstance(value, str) and len(value) > 32:
        return None
    try:
        probability = float(value)
    except (ValueError, OverflowError):
        return None
    return probability if math.isfinite(probability) and 0 <= probability <= 1 else None


def emit_trace(stage: str, provider: str, data: dict[str, Any]) -> None:
    sink = trace_sink.get()
    if sink is None:
        return
    context = {key: value for key, value in trace_context.get().items() if key in _CONTEXT_KEYS}
    metadata = {key: value for key, value in data.items() if key in _DATA_KEYS}
    for key in ("error_code", "operation", "mode", "task", "budget_status", "cost_basis"):
        if key in metadata and _tag(metadata[key]) is None:
            metadata[key] = None
    version = metadata.get("prompt_template_version")
    if version is not None and not (
        isinstance(version, str) and re.fullmatch(r"core@[0-9.]{1,20}/[A-Za-z0-9_:-]{1,100}@[0-9.]{1,20}", version)
    ):
        metadata["prompt_template_version"] = None
    if "model" in metadata and not (
        isinstance(metadata["model"], str)
        and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./:-]{0,239}", metadata["model"])
    ):
        metadata["model"] = None
    for key in ("input_hash", "output_hash"):
        if key in metadata and not (
            isinstance(metadata[key], str) and re.fullmatch(r"[a-f0-9]{64}", metadata[key])
        ):
            metadata.pop(key)
    for key in ("usage", "cost"):
        if key in metadata:
            metadata[key] = numeric_metadata(metadata[key])
    for key in ("confidence", "primary_confidence", "shadow_confidence"):
        if key in metadata:
            metadata[key] = numeric_confidence(metadata[key])
    safe_stage = stage if re.fullmatch(r"[A-Za-z0-9_:-]{1,100}", stage) else "provider_call"
    safe_provider = provider if re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", provider) else "unknown"
    try:
        sink(safe_stage, safe_provider, {**context, **metadata})
    except Exception:
        # A telemetry callback must not change the provider's return value or expose its input.
        return
