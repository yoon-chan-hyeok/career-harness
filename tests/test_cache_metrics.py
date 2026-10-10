import json
from typing import Any

import pytest
from career.cache_metrics import cache_observation, summarize_cache


def usage(inputs: Any = 100, cached: Any = 20, writes: Any = None) -> dict[str, Any]:
    return {
        "input_tokens": inputs,
        "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": writes},
    }


@pytest.mark.parametrize("value", [None, {}, {"input_tokens": 100}, usage(cached=None)])
def test_missing_cache_counters_remain_unknown(value):
    observation = cache_observation(value)
    assert observation["status"] == "UNKNOWN"
    assert observation["cached_tokens"] is None
    assert observation["hit_ratio"] is None
    assert observation["cache_write_tokens"] is None


@pytest.mark.parametrize("field", ["input_tokens", "cached_tokens", "cache_write_tokens"])
@pytest.mark.parametrize("value", [True, False, 1.0, float("nan"), float("inf"), -1, "private text"])
def test_invalid_counter_types_and_ranges_are_rejected(field, value):
    raw = usage()
    if field == "input_tokens":
        raw[field] = value
    else:
        raw["input_tokens_details"][field] = value
    observation = cache_observation(raw)
    assert observation["status"] == "INVALID"
    assert observation[field] is None
    assert observation["hit_ratio"] is None


@pytest.mark.parametrize("raw", [usage(100, 101), usage(100, 80, 21), usage(100, None, 101)])
def test_read_and_write_counters_cannot_exceed_input(raw):
    observation = cache_observation(raw)
    assert observation["status"] == "INVALID"
    assert observation["hit_ratio"] is None


def test_reported_reads_survive_missing_writes_and_chat_usage_aliases():
    expected = {
        "status": "HIT", "input_tokens": 100, "cached_tokens": 20,
        "cache_write_tokens": None, "hit_ratio": 0.2,
    }
    assert cache_observation(usage()) == expected
    assert cache_observation({
        "prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 20},
    }) == expected
    assert cache_observation({
        "input_tokens": 100, "input_tokens_details": None,
        "prompt_tokens_details": {"cached_tokens": 20},
    }) == expected


def test_observed_zero_is_a_miss_and_zero_input_has_no_ratio():
    assert cache_observation(usage(cached=0))["status"] == "MISS"
    assert cache_observation(usage(cached=0))["hit_ratio"] == 0
    assert cache_observation(usage(0, 0, 0)) == {
        "status": "MISS", "input_tokens": 0, "cached_tokens": 0,
        "cache_write_tokens": 0, "hit_ratio": None,
    }


def test_partial_reports_preserve_actual_counters_without_claiming_a_hit():
    assert cache_observation(usage(None, 20)) == {
        "status": "UNKNOWN", "input_tokens": None, "cached_tokens": 20,
        "cache_write_tokens": None, "hit_ratio": None,
    }
    assert cache_observation(usage(100, None, 10)) == {
        "status": "UNKNOWN", "input_tokens": 100, "cached_tokens": None,
        "cache_write_tokens": 10, "hit_ratio": None,
    }


@pytest.mark.parametrize("details", [[], True, "provider prose"])
def test_malformed_details_do_not_become_a_cache_miss(details):
    observation = cache_observation({"input_tokens": 100, "input_tokens_details": details})
    assert observation["status"] == "INVALID"
    assert observation["cached_tokens"] is None


def test_summary_uses_matching_reported_rows_for_weighted_ratio_and_retains_failed_usage():
    rows = [
        {"operation": "structured", "status": "FAILED", "usage": usage(100, 50)},
        {"operation": "generate", "usage": usage(900, 0)},
        {"operation": "generate", "usage": {"input_tokens": 10000}},
        {"operation": "structured", "usage": usage(2000, 2001)},
        {"operation": "embed", "usage": usage(5000, 5000)},
    ]
    assert summarize_cache(iter(rows)) == {
        "generative_calls": 4, "reported_calls": 2, "unknown_calls": 1,
        "invalid_calls": 1, "hit_calls": 1, "input_tokens": 1000,
        "cached_tokens": 50, "hit_ratio": 0.05,
    }


@pytest.mark.parametrize("rows", [[], [{"usage": None}], [{"usage": usage(cached=-1)}]])
def test_no_valid_reports_leave_token_totals_and_ratio_unknown(rows):
    summary = summarize_cache(rows)
    assert summary["reported_calls"] == summary["hit_calls"] == 0
    assert summary["input_tokens"] is summary["cached_tokens"] is summary["hit_ratio"] is None


def test_provider_counters_override_stored_claims_and_never_expose_prose_or_keys():
    private = "raw candidate source and private cache key"
    raw = usage(cached=0)
    raw["input_tokens_details"]["prose"] = {"private": private}
    rows = [{
        "usage": raw, "prompt": private, "cache_key": private,
        "cache_observation": {"status": "HIT", "cached_tokens": 100, "hit_ratio": 1},
    }]
    observation = cache_observation(raw)
    summary = summarize_cache(rows)
    assert summary["hit_calls"] == 0
    assert summary["cached_tokens"] == 0 and summary["hit_ratio"] == 0
    assert private not in json.dumps({"observation": observation, "summary": summary})
    assert set(observation) == {"status", "input_tokens", "cached_tokens", "cache_write_tokens", "hit_ratio"}
