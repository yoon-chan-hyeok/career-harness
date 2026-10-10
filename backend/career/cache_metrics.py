"""Cache observations from reported provider counters, without prompt or key data."""

from collections.abc import Iterable
from typing import Any


def _counter(value: Any) -> tuple[int | None, bool]:
    if value is None:
        return None, False
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None, True
    return value, False


def cache_observation(usage: dict | None) -> dict[str, Any]:
    """Distinguish an observed cache miss from missing or invalid counters.

    Cache writes are optional: their absence does not erase a reported read.
    Other usage fields and arbitrary provider metadata are never returned.
    """
    observation: dict[str, Any] = {
        "status": "UNKNOWN",
        "input_tokens": None,
        "cached_tokens": None,
        "cache_write_tokens": None,
        "hit_ratio": None,
    }
    if usage is None:
        return observation
    if not isinstance(usage, dict):
        return {**observation, "status": "INVALID"}

    inputs, invalid_input = _counter(usage.get("input_tokens", usage.get("prompt_tokens")))
    details = usage.get("input_tokens_details")
    if details is None:
        details = usage.get("prompt_tokens_details")
    invalid_details = details is not None and not isinstance(details, dict)
    details = details if isinstance(details, dict) else {}
    cached, invalid_cached = _counter(details.get("cached_tokens"))
    writes, invalid_writes = _counter(details.get("cache_write_tokens"))
    observation.update(input_tokens=inputs, cached_tokens=cached, cache_write_tokens=writes)

    invalid_total = inputs is not None and (
        (cached if cached is not None else 0) + (writes if writes is not None else 0) > inputs
    )
    if invalid_input or invalid_details or invalid_cached or invalid_writes or invalid_total:
        observation["status"] = "INVALID"
    elif inputs is not None and cached is not None:
        observation["status"] = "HIT" if cached > 0 else "MISS"
        if inputs > 0:
            observation["hit_ratio"] = cached / inputs
    return observation


def summarize_cache(rows: Iterable[dict]) -> dict[str, Any]:
    """Summarize trace data using the same valid reported calls for both totals.

    Failed calls still contribute their observed usage. Stored cache claims are
    ignored, and embeddings are excluded. No reports means unknown token totals.
    """
    summary: dict[str, Any] = {
        "generative_calls": 0,
        "reported_calls": 0,
        "unknown_calls": 0,
        "invalid_calls": 0,
        "hit_calls": 0,
        "input_tokens": None,
        "cached_tokens": None,
        "hit_ratio": None,
    }
    inputs = cached = 0
    for row in rows:
        if row.get("operation") == "embed":
            continue
        summary["generative_calls"] += 1
        observation = cache_observation(row.get("usage"))
        status = observation["status"]
        if status == "UNKNOWN":
            summary["unknown_calls"] += 1
        elif status == "INVALID":
            summary["invalid_calls"] += 1
        else:
            summary["reported_calls"] += 1
            summary["hit_calls"] += status == "HIT"
            inputs += observation["input_tokens"]
            cached += observation["cached_tokens"]
    if summary["reported_calls"]:
        summary.update(input_tokens=inputs, cached_tokens=cached)
        if inputs > 0:
            summary["hit_ratio"] = cached / inputs
    return summary
