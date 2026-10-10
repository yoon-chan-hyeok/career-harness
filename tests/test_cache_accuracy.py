"""Cache accuracy across sanitized provider traces, UTC periods and quota settlement."""

import json
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from career import usage_limits
from career.cache_metrics import cache_observation
from career.models import AIUsageBucket, PromptRun
from career.provider_policy import StagePolicy
from career.runtime_trace import numeric_metadata, trace_sink
from career.usage_limits import configure_usage, request_budget_scope, usage_status
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_runtime_trace import Output, sdk_provider
from test_usage_limits import ledger

PRIVATE = "private source and credential-like provider prose"


@pytest.mark.parametrize("field", ["input_tokens", "cached_tokens", "cache_write_tokens"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, 1.0, PRIVATE, {"prose": PRIVATE}])
def test_invalid_provider_counter_survives_storage_and_aggregation_without_private_values(db, monkeypatch, field, bad):
    instant = datetime(2030, 1, 8, 12, tzinfo=UTC)
    monkeypatch.setattr(usage_limits, "now", lambda: instant)
    raw: dict[str, Any] = {"input_tokens": 100, "output_tokens": 2,
                           "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}}
    if field == "input_tokens":
        raw[field] = bad
    else:
        raw["input_tokens_details"][field] = bad
    instance = sdk_provider(parsed=lambda **_kw: SimpleNamespace(output_parsed=Output(value="fresh"), usage=raw))
    token = trace_sink.set(lambda stage, provider, data: db.add(
        PromptRun(user_id="owner", created_at=instant, stage=stage, provider=provider, data=data)
    ))
    try:
        assert instance.structured("writer", {}, Output).value == "fresh"
    finally:
        trace_sink.reset(token)
    db.flush()
    db.expire_all()
    stored = db.scalar(select(PromptRun).where(PromptRun.user_id == "owner"))
    assert stored is not None
    assert stored.data["cache_status"] == "INVALID"
    assert PRIVATE not in json.dumps(stored.data, allow_nan=False)
    assert cache_observation(stored.data["usage"])["status"] == "INVALID"
    stats = usage_status(db, "owner")["daily"]["cache"]
    assert stats["invalid_calls"] == 1 and stats["unknown_calls"] == 0
    assert stats["reported_calls"] == stats["hit_calls"] == 0
    assert stats["hit_ratio"] is None


@pytest.mark.parametrize("key", ["input_tokens_details", "prompt_tokens_details"])
def test_malformed_details_remain_invalid_and_missing_details_remain_unknown(key):
    malformed = numeric_metadata({"input_tokens": 100, key: PRIVATE})
    assert cache_observation(malformed)["status"] == "INVALID"
    assert PRIVATE not in json.dumps(malformed)
    missing = numeric_metadata({"input_tokens": 100, key: None})
    assert cache_observation(missing)["status"] == "UNKNOWN"


def _trace(user: str, created: datetime) -> PromptRun:
    return PromptRun(user_id=user, created_at=created, stage="writer", provider="OpenAI", data={
        "operation": "structured", "usage": {"input_tokens": 100, "output_tokens": 2,
                                                "input_tokens_details": {"cached_tokens": 50}},
    })


@pytest.mark.parametrize("current", [datetime(2030, 1, 8, tzinfo=UTC), datetime(2030, 12, 8, tzinfo=UTC)])
def test_current_month_excludes_next_month_and_other_accounts(db, monkeypatch, current):
    monkeypatch.setattr(usage_limits, "now", lambda: current)
    following = current.replace(year=2031, month=1) if current.month == 12 else current.replace(month=2)
    db.add_all([_trace("owner", current), _trace("owner", following), _trace("other", current)])
    db.flush()
    stats = usage_status(db, "owner")
    assert stats["monthly"]["cache"]["generative_calls"] == 1
    assert stats["daily"]["cache"]["generative_calls"] == 1


def test_daily_aggregation_normalizes_aware_timestamps_and_accepts_naive_utc(monkeypatch):
    current = datetime(2030, 1, 8, 12, tzinfo=UTC)
    monkeypatch.setattr(usage_limits, "now", lambda: current)
    korea = timezone(timedelta(hours=9))
    payload = {"operation": "structured", "usage": {
        "input_tokens": 100, "input_tokens_details": {"cached_tokens": 50},
    }}
    rows = [(datetime(2030, 1, 8, 1, tzinfo=korea), payload),  # Previous UTC day.
            (datetime(2030, 1, 9, 1, tzinfo=korea), payload),  # Current UTC day.
            (current.replace(tzinfo=None), payload)]
    db = cast(Session, SimpleNamespace(scalar=lambda _query: None, execute=lambda _query: rows))
    stats = usage_status(db, "owner")
    assert stats["daily"]["cache"]["generative_calls"] == 2
    assert stats["monthly"]["cache"]["generative_calls"] == 3


def test_period_labels_and_cache_ranges_share_one_clock_read(db, monkeypatch):
    before = datetime(2030, 1, 31, 23, 59, 59, tzinfo=UTC)
    after = before + timedelta(seconds=1)
    calls = []
    def clock():
        calls.append(True)
        return before if len(calls) == 1 else after
    monkeypatch.setattr(usage_limits, "now", clock)
    db.add(_trace("owner", before))
    db.flush()
    stats = usage_status(db, "owner")
    assert len(calls) == 1
    assert stats["daily"]["period"] == "2030-01-31"
    assert stats["monthly"]["period"] == "2030-01"
    assert stats["daily"]["cache"]["generative_calls"] == 1


def test_unknown_cache_charge_keeps_ceiling_but_never_reports_it_as_an_observed_cost(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_LLM_PRICING_JSON", json.dumps({"known": {
        "input_usd_per_million": 2, "cached_input_usd_per_million": 1,
        "cache_write_usd_per_million": 3, "output_usd_per_million": 4,
    }}))
    engine = ledger(tmp_path)
    try:
        with Session(engine) as db:
            configure_usage(db, "owner", {"daily_cost_usd": 0.02})
            db.commit()
            with request_budget_scope(db, "owner", "provider_check") as quota:
                ticket = quota.draw(StagePolicy("known", max_output_tokens=100), 100)
                quota.settle_call(ticket, "known", {
                    "input_tokens": 50, "output_tokens": 20, "input_tokens_details": {},
                })
                assert ticket.charged_cost == ticket.cost and not ticket.cost_observed
            state = usage_status(db, "owner")["daily"]
            bucket = db.scalar(select(AIUsageBucket).where(AIUsageBucket.period.like("D:%")))
            assert bucket is not None and bucket.data["cost_microusd"] == ticket.cost
            assert state["tokens"] == 70 and state["unknown_cost_calls"] == 1
            assert state["estimated_cost_usd"] is state["remaining_cost_usd"] is None
            assert state["known_estimated_cost_usd"] == 0
    finally:
        engine.dispose()


def test_legacy_mixed_costs_are_not_recast_as_known_estimates(db):
    db.add(AIUsageBucket(user_id="owner", period=usage_limits._periods()[0], data={
        "cost_microusd": 1000, "unknown_cost_calls": 1,
    }))
    db.flush()
    assert usage_status(db, "owner")["daily"]["known_estimated_cost_usd"] is None
