import json

import pytest
from career.provider_policy import (
    BudgetExceeded,
    StagePolicy,
    estimated_cost,
    evaluate_response,
    stage_policy,
    validate_cost_configuration,
)


@pytest.fixture(autouse=True)
def clean_configuration(monkeypatch):
    for name in [
        "OPENAI_SMALL_MODEL",
        "OPENAI_STAGE_POLICIES",
        "OPENAI_PRICING_JSON",
        "OPENAI_TIMEOUT_SECONDS",
        "OPENAI_MAX_OUTPUT_TOKENS",
    ]:
        monkeypatch.delenv(name, raising=False)


def usage(inputs=1000, outputs=100, cached=0, writes=0):
    return {
        "input_tokens": inputs,
        "output_tokens": outputs,
        "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": writes},
    }


def test_smaller_model_requires_explicit_configuration_and_low_risk_stage(monkeypatch):
    assert stage_policy("writer", "explicit-strong").model == "explicit-strong"
    assert stage_policy("truth_extraction", "explicit-strong").model == "explicit-strong"
    monkeypatch.setenv("OPENAI_SMALL_MODEL", "explicit-small")
    assert stage_policy("truth_extraction", "explicit-strong").model == "explicit-small"
    assert stage_policy("question_type", "explicit-strong").model == "explicit-small"
    for stage in ["opportunity", "strategy", "writer", "resume_writer", "fact_reviewer", "reverse_interview"]:
        assert stage_policy(stage, "explicit-strong").model == "explicit-strong"
    monkeypatch.setenv(
        "OPENAI_STAGE_POLICIES",
        json.dumps({"truth_extraction": {"model": "explicit-reviewed-override", "timeout_seconds": 20}}),
    )
    assert stage_policy("truth_extraction", "explicit-strong").model == "explicit-reviewed-override"
    assert stage_policy("truth_extraction", "explicit-strong").timeout_seconds == 20


@pytest.mark.parametrize(
    "value",
    [
        "[]",
        '{"writer":{"invented":"unsupported"}}',
        '{"writer":{"timeout_seconds":-1}}',
        '{"writer":{"max_output_tokens":1}}',
        '{"writer":{"max_cost_usd":NaN}}',
    ],
)
def test_invalid_stage_budget_is_rejected_without_exposing_values(monkeypatch, value):
    monkeypatch.setenv("OPENAI_STAGE_POLICIES", value)
    with pytest.raises(ValueError):
        stage_policy("writer", "explicit-model")


def test_unconfigured_or_incomplete_prices_are_unknown(monkeypatch):
    assert estimated_cost("explicit-model", usage()) is None
    monkeypatch.setenv("OPENAI_PRICING_JSON", json.dumps({"explicit-model": {"input_usd_per_million": 2}}))
    assert estimated_cost("explicit-model", usage()) is None
    with pytest.raises(BudgetExceeded) as result:
        validate_cost_configuration(StagePolicy("explicit-model", max_cost_usd=0.02))
    assert result.value.code == "COST_BUDGET_UNVERIFIABLE"


def test_cost_uses_actual_ordinary_cached_write_output_and_tool_usage(monkeypatch):
    monkeypatch.setenv(
        "OPENAI_PRICING_JSON",
        json.dumps(
            {
                "explicit-model": {
                    "input_usd_per_million": 2,
                    "cached_input_usd_per_million": 0.2,
                    "cache_write_usd_per_million": 2.5,
                    "output_usd_per_million": 8,
                    "web_search_usd_per_call": 0.01,
                }
            }
        ),
    )
    # 1000 ordinary input + 2000 cached + 1000 cache writes + 100 output + two real tool calls.
    cost = estimated_cost("explicit-model", usage(4000, 100, 2000, 1000), tool_calls=2)
    assert cost == pytest.approx((2000 + 400 + 2500 + 800) / 1_000_000 + 0.02)
    assert estimated_cost("explicit-model", usage(4000, 100, 2000, 1000), tool_calls=None) is None
    assert estimated_cost("explicit-model", {"input_tokens": 100, "output_tokens": 5}) is None
    assert estimated_cost("explicit-model", usage(100, 5, cached=101)) is None


def test_actual_latency_input_output_and_cost_block_result_acceptance(monkeypatch):
    model = "explicit-model"
    with pytest.raises(BudgetExceeded) as result:
        evaluate_response(StagePolicy(model, timeout_seconds=2), usage(), latency_ms=2001)
    assert result.value.code == "LATENCY_BUDGET_EXCEEDED"
    with pytest.raises(BudgetExceeded) as result:
        evaluate_response(StagePolicy(model, max_output_tokens=99), usage(), latency_ms=1)
    assert result.value.code == "OUTPUT_TOKEN_BUDGET_EXCEEDED"
    with pytest.raises(BudgetExceeded) as result:
        evaluate_response(StagePolicy(model, max_input_tokens=999), usage(), latency_ms=1)
    assert result.value.code == "INPUT_TOKEN_BUDGET_EXCEEDED"
    with pytest.raises(BudgetExceeded) as result:
        evaluate_response(StagePolicy(model, max_input_tokens=999), None, latency_ms=1)
    assert result.value.code == "TOKEN_BUDGET_UNVERIFIABLE"
    monkeypatch.setenv(
        "OPENAI_PRICING_JSON",
        json.dumps(
            {
                model: {
                    "input_usd_per_million": 2,
                    "output_usd_per_million": 8,
                    "cached_input_usd_per_million": 0.2,
                    "cache_write_usd_per_million": 2.5,
                }
            }
        ),
    )
    validate_cost_configuration(StagePolicy(model, max_cost_usd=0.001))
    with pytest.raises(BudgetExceeded) as result:
        evaluate_response(StagePolicy(model, max_cost_usd=0.001), usage(), latency_ms=1)
    assert result.value.code == "COST_BUDGET_EXCEEDED"
    result = evaluate_response(StagePolicy(model, max_cost_usd=0.01), usage(), latency_ms=1)
    assert result["cost"] == pytest.approx(0.0028)


def test_embeddings_use_prompt_usage_without_invented_generated_tokens(monkeypatch):
    monkeypatch.setenv(
        "OPENAI_PRICING_JSON", json.dumps({"explicit-embedding": {"input_usd_per_million": 0.1}})
    )
    assert estimated_cost("explicit-embedding", {"prompt_tokens": 100, "total_tokens": 100}) == pytest.approx(
        0.00001
    )
