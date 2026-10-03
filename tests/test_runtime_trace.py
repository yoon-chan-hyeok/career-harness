import json
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from career.decisions import Decision, JevDecisionProvider, LLMStructuredDecisionProvider, shadow_decision
from career.models import PromptRun
from career.providers import FakeLLMProvider, OpenAIProvider, OpenAIWebResearchProvider, ProviderUnavailable
from career.runtime_trace import emit_trace, input_hash, trace_context, trace_sink
from career.schemas import ResearchResult
from pydantic import BaseModel
from sqlalchemy import select

PRIVATE = "PRIVATE_PROMPT_RESPONSE_AND_ERROR_MUST_NOT_APPEAR"


class Output(BaseModel):
    value: str


@contextmanager
def capture():
    rows = []
    threads = []

    def sink(stage, provider, data):
        rows.append({"stage": stage, "provider": provider, "data": data})
        threads.append(threading.get_ident())

    sink_token = trace_sink.set(sink)
    context_token = trace_context.set(
        {
            "workspace_id": "workspace-fixture",
            "execution_run_id": "run-fixture",
            "input_artifact_ids": ["artifact-fixture"],
            "prompt_version": "v1",
            "prompt": PRIVATE,
        }
    )
    try:
        yield rows, threads
    finally:
        trace_sink.reset(sink_token)
        trace_context.reset(context_token)


def usage():
    return SimpleNamespace(
        model_dump=lambda: {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
            "input_tokens_details": {"cached_tokens": 2},
            "unexpected_text": PRIVATE,
        }
    )


def sdk_provider(parsed=None, created=None, embedded=None):
    provider = object.__new__(OpenAIProvider)
    provider.model = "fixture-openai"
    provider.last_trace = {}
    setattr(
        provider,
        "client",
        SimpleNamespace(
            responses=SimpleNamespace(parse=parsed, create=created),
            embeddings=SimpleNamespace(create=embedded),
        ),
    )
    return provider


def test_openai_calls_emit_operational_metadata_without_input_or_response():
    requests = []

    def parse(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(output_parsed=Output(value=PRIVATE), usage=usage(), status="completed")

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(output_text=PRIVATE, usage=usage(), status="completed")

    def embed(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.25, 0.75])],
                               usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 11, "total_tokens": 11}))

    provider = sdk_provider(parse, create, embed)
    with capture() as (rows, _):
        assert provider.structured("writer", {"private": PRIVATE}, Output).value == PRIVATE
        assert provider.generate("generate", {"private": PRIVATE}) == PRIVATE
        assert provider.embed([PRIVATE]) == [[0.25, 0.75]]
    assert [row["stage"] for row in rows] == ["writer", "generate", "embedding"]
    assert PRIVATE not in json.dumps(rows)
    assert requests[0]["store"] is False and requests[1]["store"] is False
    assert PRIVATE in requests[0]["input"] and requests[2]["input"] == [PRIVATE]
    for row in rows:
        data = row["data"]
        assert data["status"] == "COMPLETED"
        assert data["workspace_id"] == "workspace-fixture"
        assert data["execution_run_id"] == "run-fixture"
        assert data["input_artifact_ids"] == ["artifact-fixture"]
        if row["stage"] == "embedding":
            assert data["usage"] == {"prompt_tokens": 11, "total_tokens": 11}
        else:
            assert data["usage"]["total_tokens"] == 18
            assert data["usage"]["input_tokens_details"]["cached_tokens"] == 2
        assert data["cost"] is None and data["retry_count"] is None
        assert data["latency_ms"] >= 0 and len(data["input_hash"]) == 64


@pytest.mark.parametrize("operation", ["structured", "generate", "embed"])
def test_openai_sdk_failure_is_publicly_safe_and_recorded(operation):
    def fail(**_kwargs):
        raise RuntimeError(PRIVATE)

    provider = sdk_provider(fail, fail, fail)
    with capture() as (rows, _), pytest.raises(ProviderUnavailable) as error:
        if operation == "structured":
            provider.structured("writer", {"private": PRIVATE}, Output)
        elif operation == "generate":
            provider.generate("writer", {"private": PRIVATE})
        else:
            provider.embed([PRIVATE])
    assert PRIVATE not in str(error.value)
    assert len(rows) == 1 and PRIVATE not in json.dumps(rows)
    assert rows[0]["data"]["status"] == "FAILED"
    assert rows[0]["data"]["usage"] is None
    assert rows[0]["data"]["retry_count"] is None
    assert provider.last_trace["status"] == "FAILED"


def test_structured_validation_failure_preserves_observed_usage():
    provider = sdk_provider(
        parsed=lambda **_kw: SimpleNamespace(
            output_parsed=None,
            status="completed",
            usage=usage(),
        )
    )
    with capture() as (rows, _), pytest.raises(ProviderUnavailable):
        provider.structured("writer", {"private": PRIVATE}, Output)
    assert rows[0]["data"]["status"] == "FAILED"
    assert rows[0]["data"]["usage"]["total_tokens"] == 18
    assert rows[0]["data"]["error_code"] == "PROVIDER_RESPONSE_INVALID"


@pytest.mark.parametrize("status", ["failed", "incomplete"])
def test_generate_never_calls_incomplete_response_success(status):
    provider = sdk_provider(
        created=lambda **_kw: SimpleNamespace(
            output_text=PRIVATE,
            status=status,
            usage=usage(),
        )
    )
    with capture() as (rows, _), pytest.raises(ProviderUnavailable):
        provider.generate("writer", {})
    assert rows[0]["data"]["status"] == "FAILED"


def test_trace_callback_failure_does_not_change_provider_return():
    provider = sdk_provider(
        parsed=lambda **_kw: SimpleNamespace(
            output_parsed=Output(value="same"),
            usage=None,
        )
    )

    def fail_sink(*_args):
        raise RuntimeError(PRIVATE)

    token = trace_sink.set(fail_sink)
    try:
        assert provider.structured("writer", {}, Output).value == "same"
    finally:
        trace_sink.reset(token)


def test_runtime_sink_filters_raw_text_and_provider_usage_prose():
    with capture() as (rows, _):
        emit_trace(
            "writer",
            "OpenAI",
            {
                "prompt": PRIVATE,
                "context": PRIVATE,
                "response": PRIVATE,
                "error": PRIVATE,
                "input_hash": input_hash(PRIVATE),
                "usage": {"input_tokens": 3, "text": PRIVATE},
                "model": "not a model " + PRIVATE,
                "cost": None,
            },
        )
    assert PRIVATE not in json.dumps(rows)
    assert rows[0]["data"]["usage"] == {"input_tokens": 3}
    assert "prompt" not in rows[0]["data"] and rows[0]["data"]["model"] is None


def research_result():
    return ResearchResult(
        official_facts=[],
        external_evidence=[],
        role_signals=[],
        historical_jd_signals=[],
        selection_process_signals=[],
        inferences=[],
        sources=[],
    )


def test_web_search_and_extraction_have_separate_real_call_traces():
    provider = sdk_provider(
        parsed=lambda **_kw: SimpleNamespace(output_parsed=research_result(), usage=usage()),
        created=lambda **_kw: SimpleNamespace(output_text=PRIVATE, output=[], usage=usage()),
    )
    with capture() as (rows, _):
        result = OpenAIWebResearchProvider(provider).research("fixture", "fixture", PRIVATE)
    assert result.sources == []
    assert [row["stage"] for row in rows] == ["web_search", "research_extract"]
    assert all(row["data"]["status"] == "COMPLETED" for row in rows)
    assert PRIVATE not in json.dumps(rows)


def test_web_search_sdk_failure_records_failure_without_extracting():
    def fail(**_kw):
        raise RuntimeError(PRIVATE)

    provider = sdk_provider(created=fail)
    with capture() as (rows, _), pytest.raises(ProviderUnavailable):
        OpenAIWebResearchProvider(provider).research("fixture", "fixture", PRIVATE)
    assert len(rows) == 1 and rows[0]["stage"] == "web_search"
    assert rows[0]["data"]["status"] == "FAILED"


def test_bounded_openai_decision_emits_once_and_validates_allowed_option():
    provider = sdk_provider(
        parsed=lambda **_kw: SimpleNamespace(
            output_parsed=Decision(choice="yes", confidence="HIGH", rationale=PRIVATE),
            usage=usage(),
        )
    )
    with capture() as (rows, _):
        result = LLMStructuredDecisionProvider(provider).choose(
            "direct_answer", {"text": PRIVATE}, ["yes", "no"]
        )
    assert result.choice == "yes" and len(rows) == 1
    assert rows[0]["data"]["operation"] == "bounded_decision"
    assert PRIVATE not in json.dumps(rows)
    with capture() as (failed, _), pytest.raises(ProviderUnavailable):
        LLMStructuredDecisionProvider(provider).choose("direct_answer", {}, ["no"])
    assert len(failed) == 1 and failed[0]["data"]["status"] == "FAILED"


def test_bounded_injected_provider_receives_fallback_trace_once():
    provider = FakeLLMProvider(
        {"direct_answer": {"choice": "yes", "confidence": "HIGH", "rationale": PRIVATE}}
    )
    with capture() as (rows, _):
        assert LLMStructuredDecisionProvider(provider).binary("direct_answer", {"text": PRIVATE})
    assert len(rows) == 1 and rows[0]["provider"] == "FakeLLMProvider"
    assert rows[0]["data"]["status"] == "COMPLETED" and PRIVATE not in json.dumps(rows)


def test_jev_http_failure_normalizes_response_body_and_records_attempt(monkeypatch):
    original = httpx.Client
    monkeypatch.setenv("JEV_API_KEY", "fixture-key")
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda _request: httpx.Response(503, text=PRIVATE)),
            **kwargs,
        ),
    )
    with capture() as (rows, _), pytest.raises(ProviderUnavailable) as error:
        JevDecisionProvider().choose("direct_answer", {"text": PRIVATE}, ["yes", "no"])
    assert PRIVATE not in str(error.value) and PRIVATE not in json.dumps(rows)
    assert len(rows) == 1 and rows[0]["data"]["error_code"] == "PROVIDER_HTTP_FAILED"
    assert rows[0]["data"]["cost"] is None and rows[0]["data"]["usage"] is None


def test_jev_shadow_keeps_primary_and_emits_collected_trace_on_main_thread(db):
    main_thread = threading.get_ident()
    primary = LLMStructuredDecisionProvider(
        FakeLLMProvider(
            {
                "direct_answer": {"choice": "yes", "confidence": "HIGH", "rationale": PRIVATE},
            }
        )
    )
    shadow = JevDecisionProvider(
        transport=lambda *_args: {
            "choice": "no",
            "confidence": "0.9",
            "rationale": PRIVATE,
        }
    )
    with capture() as (rows, threads):
        result = shadow_decision(
            db, "fixture", primary, shadow, "direct_answer", {"text": PRIVATE}, ["yes", "no"]
        )
    assert result.choice == "yes"
    assert len(rows) == 2 and all(thread == main_thread for thread in threads)
    assert rows[1]["provider"] == "Jev"
    assert rows[1]["data"]["workspace_id"] == "workspace-fixture"
    db.flush()
    diagnostics = db.scalar(select(PromptRun)).data
    assert diagnostics["disagreement"] is True
    assert "primary" not in diagnostics and "shadow" not in diagnostics
    assert PRIVATE not in json.dumps(diagnostics) and PRIVATE not in json.dumps(rows)


def test_shadow_timeout_is_observed_without_invented_cost_or_usage(db):
    release = threading.Event()

    def delayed(*_args):
        release.wait(1)
        return {"choice": "no", "confidence": "0.9", "rationale": PRIVATE}

    primary = LLMStructuredDecisionProvider(
        FakeLLMProvider(
            {
                "direct_answer": {"choice": "yes", "confidence": "HIGH", "rationale": PRIVATE},
            }
        )
    )
    try:
        with capture() as (rows, _):
            result = shadow_decision(
                db,
                "fixture",
                primary,
                JevDecisionProvider(transport=delayed),
                "direct_answer",
                {},
                ["yes", "no"],
                timeout=0.001,
            )
        assert result.choice == "yes"
        timeout = next(row for row in rows if row["provider"] == "Jev")
        assert timeout["data"]["error_code"] == "SHADOW_TIMEOUT"
        assert timeout["data"]["usage"] is None and timeout["data"]["cost"] is None
        assert timeout["data"]["retry_count"] is None
    finally:
        release.set()


def test_actual_sdk_request_uses_stage_model_and_explicit_caps(monkeypatch):
    calls = []
    monkeypatch.setenv("OPENAI_SMALL_MODEL", "fixture-small")
    monkeypatch.setenv(
        "OPENAI_STAGE_POLICIES",
        json.dumps(
            {
                "question_type": {"timeout_seconds": 3, "max_output_tokens": 64},
            }
        ),
    )

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=Output(value="same"), usage=usage())

    provider = sdk_provider(parsed=parse)
    with capture() as (rows, _):
        provider.structured("question_type", {}, Output)
        provider.structured("writer", {}, Output)
    assert calls[0]["model"] == "fixture-small"
    assert calls[0]["timeout"] == 3 and calls[0]["max_output_tokens"] == 64
    assert calls[1]["model"] == "fixture-openai"
    assert rows[0]["data"]["model"] == "fixture-small"
    assert rows[0]["data"]["budget_status"] == "WITHIN_CONFIGURED_LIMITS"


def test_unenforceable_explicit_cost_cap_stops_before_api_call(monkeypatch):
    calls = []
    monkeypatch.setenv("OPENAI_STAGE_POLICIES", json.dumps({"writer": {"max_cost_usd": 0.01}}))
    monkeypatch.setenv("OPENAI_PRICING_JSON", "{}")
    provider = sdk_provider(parsed=lambda **kwargs: calls.append(kwargs))
    with capture() as (rows, _), pytest.raises(ProviderUnavailable):
        provider.structured("writer", {}, Output)
    assert not calls
    assert rows[0]["data"]["error_code"] == "COST_BUDGET_UNVERIFIABLE"
    assert rows[0]["data"]["cost"] is None
    assert rows[0]["data"]["budget_status"] == "UNVERIFIABLE"


def test_observed_input_budget_failure_is_not_accepted_as_result(monkeypatch):
    monkeypatch.setenv("OPENAI_STAGE_POLICIES", json.dumps({"writer": {"max_input_tokens": 10000}}))
    observed = {**usage().model_dump(), "input_tokens": 11000, "total_tokens": 11007}
    provider = sdk_provider(
        parsed=lambda **_kwargs: SimpleNamespace(output_parsed=Output(value="same"), usage=SimpleNamespace(model_dump=lambda: observed))
    )
    with capture() as (rows, _), pytest.raises(ProviderUnavailable):
        provider.structured("writer", {}, Output)
    assert rows[0]["data"]["error_code"] == "INPUT_TOKEN_BUDGET_EXCEEDED"
    assert rows[0]["data"]["usage"]["input_tokens"] == 11000
    assert rows[0]["data"]["status"] == "FAILED"


def test_explicit_price_estimate_is_retained_on_cost_budget_failure(monkeypatch):
    monkeypatch.setenv("OPENAI_STAGE_POLICIES", json.dumps({"writer": {"max_cost_usd": 0.1}}))
    monkeypatch.setenv(
        "OPENAI_PRICING_JSON",
        json.dumps(
            {
                "fixture-openai": {
                    "input_usd_per_million": 2,
                    "cached_input_usd_per_million": 1,
                    "cache_write_usd_per_million": 2,
                    "output_usd_per_million": 4,
                }
            }
        ),
    )
    observed = {**usage().model_dump(), "input_tokens": 100000, "total_tokens": 100007}
    provider = sdk_provider(parsed=lambda **_kwargs: SimpleNamespace(
        output_parsed=Output(value="same"), usage=SimpleNamespace(model_dump=lambda: observed)))
    with capture() as (rows, _), pytest.raises(ProviderUnavailable):
        provider.structured("writer", {}, Output)
    assert rows[0]["data"]["error_code"] == "COST_BUDGET_EXCEEDED"
    assert rows[0]["data"]["cost"] == pytest.approx(0.200026)
    assert rows[0]["data"]["cost_basis"] == "CONFIGURED_RATE_FINAL_RESPONSE_ESTIMATE"


def test_web_cost_counts_only_observed_search_calls(monkeypatch):
    monkeypatch.setenv(
        "OPENAI_PRICING_JSON",
        json.dumps(
            {
                "fixture-openai": {
                    "input_usd_per_million": 2,
                    "cached_input_usd_per_million": 1,
                    "cache_write_usd_per_million": 2,
                    "output_usd_per_million": 4,
                    "web_search_usd_per_call": 0.01,
                }
            }
        ),
    )
    provider = sdk_provider(
        parsed=lambda **_kw: SimpleNamespace(output_parsed=research_result(), usage=usage()),
        created=lambda **_kw: SimpleNamespace(
            output_text=PRIVATE,
            output=[SimpleNamespace(type="web_search_call")] * 2,
            usage=usage(),
        ),
    )
    with capture() as (rows, _):
        OpenAIWebResearchProvider(provider).research("fixture", "fixture", PRIVATE)
    assert rows[0]["data"]["tool_calls"] == 2
    assert rows[0]["data"]["cost"] == 0.020048
