import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from career.models import PromptRun
from career.prompt_cache import identity_scope, prepare
from career.provider_policy import StagePolicy, estimated_cost, evaluate_response, token_totals
from career.runtime_trace import emit_trace, trace_sink
from career.usage_limits import CallTicket, UsageEnvelope, usage_envelope, usage_status
from test_compatible_providers import Output, client, result
from test_runtime_trace import sdk_provider


@pytest.fixture(autouse=True)
def cache_settings(monkeypatch):
    monkeypatch.setenv("CAREER_PROMPT_CACHE_ENABLED", "1")
    monkeypatch.setenv("CAREER_PROMPT_CACHE_SECRET", "synthetic-cache-salt-at-least-32-bytes")


def prompt(context=None, **changes):
    arguments = {"stage": "writer", "context": context or {}, "instructions": "trusted role",
                 "model": "fixture-model", "provider": "openai", "schema": {"type": "object"}}
    return prepare(**{**arguments, **changes})


def test_wire_prefix_is_stable_without_reordering_ranked_lists_or_mutating_sources():
    left = {"document": "old draft", "evidence": [{"z": 1, "a": "확인된 원문"}, {"id": "second"}],
            "canonical_profile": {"z": 2, "a": 1}, "supplemental_guidance": {"references": []}}
    right = {key: left[key] for key in reversed(left)}
    right["canonical_profile"] = {"a": 1, "z": 2}
    with identity_scope("synthetic-owner"):
        a, b = prompt(left), prompt(right)
        c = prompt({**right, "document": "new draft"})
    assert a.content == b.content and a.key == b.key == c.key
    assert a.content.index('"canonical_profile"') < a.content.index('"document"')
    assert a.content[:a.content.index('"document"')] == c.content[:c.content.index('"document"')]
    assert json.loads(a.content)["context"]["evidence"] == left["evidence"]
    assert left["document"] == "old draft" and "new draft" in c.content
    assert "new draft" not in a.content


@pytest.mark.parametrize("changes", [
    {"provider": "huggingface"}, {"model": "another-model"}, {"stage": "resume_writer"},
    {"instructions": "changed trusted role"}, {"schema": {"type": "string"}},
    {"context": {"document_domain": "resume"}},
    {"context": {"supplemental_guidance": {"references": [{"key": "rule", "version": "2", "content_hash": "different"}]}}},
])
def test_group_changes_branch_the_key(changes):
    with identity_scope("synthetic-owner"):
        original, changed = prompt(), prompt(**changes)
    assert original.key != changed.key


def test_owner_partition_is_opaque_and_never_taken_from_input_fields():
    with identity_scope("first-private-owner"):
        a = prompt({"user_id": "second-private-owner"})
    with identity_scope("second-private-owner"):
        b = prompt({"user_id": "second-private-owner"})
    assert a.key != b.key
    assert json.loads(a.content)["request_partition"] != json.loads(b.content)["request_partition"]
    assert "first-private-owner" not in a.content and "first-private-owner" not in (a.key or "")
    assert len(a.key or "") <= 64
    anonymous_a, anonymous_b = prompt(), prompt()
    assert anonymous_a.key is anonymous_b.key is None
    assert anonymous_a.scope == "REQUEST" and anonymous_a.content != anonymous_b.content


def test_authenticated_envelope_is_used_and_cannot_disagree_with_service_identity():
    token = usage_envelope.set(cast(UsageEnvelope, SimpleNamespace(user="envelope-owner")))
    try:
        a, b = prompt(), prompt()
        assert a.scope == "USER" and a.key == b.key
        with identity_scope("different-owner"), pytest.raises(ValueError, match="계정 범위"):
            prompt()
    finally:
        usage_envelope.reset(token)
    assert prompt().key is None


def test_parallel_scopes_reset_after_exception():
    def worker(user):
        key: str | None = None
        with identity_scope(user):
            try:
                key = prompt().key
                raise RuntimeError("synthetic")
            except RuntimeError:
                assert prompt().key == key
        return key, prompt().key
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(worker, ["first-owner", "second-owner"]))
    assert a[0] != b[0] and a[1] is b[1] is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {"unsupported"}, object(), {1: "invalid key"}])
def test_unsupported_or_unstable_context_is_rejected_without_value_exposure(value):
    with pytest.raises(ValueError) as error:
        prompt({"item": value})
    assert "unsupported" not in str(error.value)


def test_disable_switch_restores_legacy_wire_and_does_not_request_retention(monkeypatch):
    monkeypatch.setenv("CAREER_PROMPT_CACHE_ENABLED", "0")
    context = {"z": 1, "a": "unchanged"}
    with identity_scope("synthetic-owner"):
        prepared = prompt(context)
    assert prepared.content == json.dumps(context, ensure_ascii=False)
    assert prepared.instructions == "trusted role" and prepared.key is None and prepared.scope == "DISABLED"


@pytest.mark.parametrize("provider", ["huggingface", "groq"])
@pytest.mark.parametrize("cached,expected", [(None, "UNKNOWN"), (0, "MISS"), (10, "HIT"),
                                             (True, "INVALID"), ("10", "INVALID"), (99, "INVALID")])
def test_free_provider_wire_stability_and_real_cache_observation(provider, cached, expected):
    import httpx2 as httpx

    calls = []
    def handle(request):
        calls.append(json.loads(request.content))
        response = result({"message": "new output"})
        if cached is not None:
            response["usage"]["prompt_tokens_details"] = {"cached_tokens": cached}
        return httpx.Response(200, json=response)

    instance = client(handle, provider)
    rows = []
    sink = trace_sink.set(lambda stage, name, data: rows.append(data))
    try:
        with identity_scope("private-cache-owner"):
            assert instance.structured("writer", {"b": 2, "a": 1}, Output).message == "new output"
            assert instance.structured("writer", {"a": 1, "b": 2}, Output).message == "new output"
        assert len(calls) == 2  # Every request generates anew; no response memoization.
        assert calls[0] == calls[1]
        assert not {"prompt_cache_key", "prompt_cache_retention", "prompt_cache_options", "extra_body"} & calls[0].keys()
        assert instance.last_trace["cache_status"] == expected
        assert token_totals(instance.last_trace["usage"]) == (21, 9)
        assert "private-cache-owner" not in json.dumps(rows)
        if cached is None:
            assert "cached_tokens" not in instance.last_trace["usage"]["input_tokens_details"]
    finally:
        trace_sink.reset(sink)
        instance.client.close()


def test_openai_receives_only_scoped_key_and_retains_store_false():
    requests = []
    def parse(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(output_parsed=Output(message="fresh"), status="completed",
                               usage={"input_tokens": 20, "output_tokens": 3,
                                      "input_tokens_details": {"cached_tokens": 10}})
    instance = sdk_provider(parsed=parse)
    with identity_scope("private-openai-owner"):
        instance.structured("writer", {"a": 1}, Output)
        instance.structured("writer", {"a": 2}, Output)
    assert requests[0]["prompt_cache_key"] == requests[1]["prompt_cache_key"]
    assert requests[0]["store"] is False
    assert not {"prompt_cache_retention", "prompt_cache_options", "previous_response_id"} & requests[0].keys()
    instance.structured("writer", {"a": 1}, Output)
    assert "prompt_cache_key" not in requests[2]


def test_cache_metadata_sanitizer_rejects_prose_and_unhashable_values():
    rows = []
    token = trace_sink.set(lambda stage, name, data: rows.append(data))
    try:
        emit_trace("writer", "OpenAI", {"cache_status": {"secret": "PRIVATE"}, "prompt_cache_scope": ["PRIVATE"],
                                          "cache_input_tokens": True, "cache_hit_ratio": "0.5",
                                          "prompt_cache_key": "PRIVATE", "prompt_cache_layout_version": "PRIVATE"})
    finally:
        trace_sink.reset(token)
    assert len(rows) == 1 and "PRIVATE" not in json.dumps(rows)
    assert rows[0]["cache_status"] is rows[0]["cache_hit_ratio"] is None


def test_unknown_cache_preserves_quota_and_unknown_cost(monkeypatch):
    rates = {"input_usd_per_million": 2, "cached_input_usd_per_million": 1,
             "cache_write_usd_per_million": 3, "output_usd_per_million": 4}
    monkeypatch.setenv("CAREER_LLM_PRICING_JSON", json.dumps({"fixture-model": rates}))
    usage = {"input_tokens": 20, "output_tokens": 3, "input_tokens_details": {}}
    assert estimated_cost("fixture-model", usage) is None
    assert evaluate_response(StagePolicy("fixture-model", max_input_tokens=30), usage, 1)["cost"] is None
    envelope = UsageEnvelope(None, "user", "reservation", 1, 1000, 100, False)
    ticket = CallTicket(1000, 100)
    envelope.settle_call(ticket, "fixture-model", usage)
    assert ticket.charged_tokens == 23 and ticket.charged_cost == 100
    usage["input_tokens_details"]["cached_tokens"] = 99
    envelope.settle_call(ticket, "fixture-model", usage)
    assert ticket.charged_tokens == 23 and estimated_cost("fixture-model", usage) is None


def test_usage_cache_periods_are_owner_scoped_and_exclude_embeddings(db, monkeypatch):
    from career import usage_limits

    current = datetime(2030, 1, 8, 12, tzinfo=UTC)
    monkeypatch.setattr(usage_limits, "now", lambda: current)
    def row(user, created, cached, operation="structured", provider="OpenAI"):
        data: dict[str, Any] = {"operation": operation, "usage": {"input_tokens": 100, "output_tokens": 2,
                                                                 "input_tokens_details": {"cached_tokens": cached}}}
        return PromptRun(user_id=user, created_at=created, stage="writer", provider=provider, data=data)
    db.add_all([row("owner", current, 60), row("owner", current.replace(day=1), 20),
                row("other", current, 99), row("owner", current, 0, "embed"),
                row("owner", current.replace(month=12, year=2029), 99),
                row("owner", current, 99, provider="fake-test-only")])
    db.flush()
    stats = usage_status(db, "owner")
    assert stats["daily"]["cache"]["generative_calls"] == 1
    assert stats["daily"]["cache"]["hit_ratio"] == 0.6
    assert stats["monthly"]["cache"]["generative_calls"] == 2
    assert stats["monthly"]["cache"]["hit_ratio"] == 0.4
    assert usage_status(db, "empty-user")["monthly"]["cache"]["hit_ratio"] is None
