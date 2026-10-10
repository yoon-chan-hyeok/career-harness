"""Explicit per-stage models and budgets; unknown prices remain unknown, never zero."""

import json
import math
import os
import re
from dataclasses import dataclass
from typing import Any

LOW_RISK_STAGES = frozenset(
    {
        "truth_extraction",
        "question_type",
        "role_noun_alignment",
        "direct_answer",
        "jargon_overload",
        "revision_routing",
        "style_projection",
        "summarization",
        "research_extract",
        "research_source_extract",
    }
)
POLICY_FIELDS = frozenset(
    {"model", "timeout_seconds", "max_output_tokens", "max_input_tokens", "max_cost_usd"}
)
PRICE_FIELDS = frozenset(
    {
        "input_usd_per_million",
        "cached_input_usd_per_million",
        "cache_write_usd_per_million",
        "output_usd_per_million",
        "web_search_usd_per_call",
    }
)


class BudgetExceeded(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        messages = {
            "REQUEST_DEADLINE_EXCEEDED": "전체 AI 처리 시간이 끝났습니다. 미완료 결과는 승인·저장하지 않았습니다. 현재 문서를 확인한 뒤 다시 실행해 주세요.",
            "INPUT_TOKEN_BUDGET_EXCEEDED": "AI에 보낼 자료가 입력 한도를 넘습니다. 문항·문서를 하나 선택하거나 원자료를 나누어 주세요. 핵심 근거를 자동으로 삭제하지 않았습니다.",
            "USAGE_LIMIT_EXCEEDED": "설정한 일·월 AI 사용 한도에 도달했습니다. 사용량 설정을 확인하거나 직접 작성해 주세요. 제공자 잔액과는 별도의 앱 실행 한도입니다.",
        }
        super().__init__(messages.get(code, "단계별 AI 실행 한도를 확인해 주세요. 기존 자료는 유지됩니다."))


@dataclass(frozen=True)
class StagePolicy:
    model: str
    timeout_seconds: float = 60
    max_output_tokens: int = 16384
    max_input_tokens: int | None = None
    max_cost_usd: float | None = None


def _object_setting(name: str) -> dict[str, Any]:
    generic = name.replace("OPENAI_", "CAREER_LLM_", 1)
    raw = os.getenv(generic, os.getenv(name, "{}"))
    try:
        if len(raw) > 65536:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise ValueError(name + " must be a bounded JSON object") from None


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(name + " must be a finite number")
    if not minimum <= value <= maximum:
        raise ValueError(name + " is outside its allowed range")
    return float(value)


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    number = _number(value, name, minimum, maximum)
    if not number.is_integer():
        raise ValueError(name + " must be an integer")
    return int(number)


def _model(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./:-]{0,239}", value):
        raise ValueError("Stage model must be an explicit model identifier")
    return value


def stage_policy(stage: str, default_model: str) -> StagePolicy:
    """Only extraction/classification stages automatically use the explicitly configured smaller model."""
    if not re.fullmatch(r"[A-Za-z0-9_:-]{1,100}", stage):
        raise ValueError("Invalid provider stage identifier")
    model = _model(default_model)
    small = os.getenv("CAREER_LLM_SMALL_MODEL", os.getenv("OPENAI_SMALL_MODEL", "")).strip()
    if stage in LOW_RISK_STAGES and small:
        model = _model(small)
    configured = _object_setting("OPENAI_STAGE_POLICIES")
    for name, item in configured.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_:-]{1,100}", name):
            raise ValueError("OPENAI_STAGE_POLICIES contains an invalid stage")
        if not isinstance(item, dict) or set(item) - POLICY_FIELDS:
            raise ValueError("OPENAI_STAGE_POLICIES contains unsupported policy fields")
    policy = configured.get(stage, {})
    model = _model(policy.get("model", model))
    try:
        global_timeout = float(os.getenv("CAREER_LLM_TIMEOUT_SECONDS", os.getenv("OPENAI_TIMEOUT_SECONDS", "60")))
        global_output = int(os.getenv("CAREER_LLM_MAX_OUTPUT_TOKENS", os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "16384")))
    except ValueError:
        raise ValueError("Global OpenAI timeout/output settings must be numbers") from None
    timeout = _number(policy.get("timeout_seconds", global_timeout), "timeout_seconds", 1, 300)
    output = _integer(policy.get("max_output_tokens", global_output), "max_output_tokens", 16, 128000)
    input_limit = policy.get("max_input_tokens")
    cost_limit = policy.get("max_cost_usd")
    return StagePolicy(
        model,
        timeout,
        output,
        _integer(input_limit, "max_input_tokens", 1, 2_000_000) if input_limit is not None else None,
        _number(cost_limit, "max_cost_usd", 0, 1000) if cost_limit is not None else None,
    )


def pricing() -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for model, configured in _object_setting("OPENAI_PRICING_JSON").items():
        key = _model(model)
        if not isinstance(configured, dict) or set(configured) - PRICE_FIELDS:
            raise ValueError("OPENAI_PRICING_JSON contains unsupported price fields")
        result[key] = {name: _number(value, name, 0, 10000) for name, value in configured.items()}
    return result


def _usage_count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def token_totals(usage: dict[str, Any] | None) -> tuple[int, int] | None:
    """Actual token quota is independent of an optional cache breakdown."""
    if not isinstance(usage, dict):
        return None
    input_tokens = _usage_count(usage.get("input_tokens", usage.get("prompt_tokens")))
    # Embeddings have prompt_tokens/total_tokens and no generation output.
    output_tokens = _usage_count(usage.get("output_tokens", usage.get("completion_tokens", 0 if "prompt_tokens" in usage else None)))
    return (input_tokens, output_tokens) if input_tokens is not None and output_tokens is not None else None


def usage_counts(usage: dict[str, Any] | None) -> tuple[int, int, int, int] | None:
    totals = token_totals(usage)
    if totals is None or not isinstance(usage, dict):
        return None
    input_tokens, output_tokens = totals
    details = usage.get("input_tokens_details") or {}
    if not isinstance(details, dict):
        return None
    cached = _usage_count(details.get("cached_tokens", 0))
    writes = _usage_count(details.get("cache_write_tokens", 0))
    if input_tokens is None or output_tokens is None or cached is None or writes is None:
        return None
    if cached + writes > input_tokens:
        return None
    return input_tokens, output_tokens, cached, writes


def estimated_input_tokens(request_data: dict[str, Any]) -> int:
    """Conservative byte bound includes Korean, system text, JSON and schema.

    A byte is an upper bound for byte-level BPE tokenization; the fixed allowance
    covers message framing. This deliberately overestimates instead of slicing
    evidence or pretending a character/4 estimate applies to Korean.
    """
    encoded = json.dumps(request_data, ensure_ascii=False, separators=(",", ":"), default=str)
    return len(encoded.encode("utf-8")) + 256


def validate_request_input(policy: StagePolicy, request_data: dict[str, Any]) -> int:
    estimate = estimated_input_tokens(request_data)
    if policy.max_input_tokens is not None and estimate > policy.max_input_tokens:
        raise BudgetExceeded("INPUT_TOKEN_BUDGET_EXCEEDED")
    return estimate


def estimated_cost(model: str, usage: dict[str, Any] | None, tool_calls: int | None = 0) -> float | None:
    """Final response token/tool estimate in USD; not a provider invoice or failed-attempt charge."""
    counts = usage_counts(usage)
    rates = pricing().get(model)
    if (
        isinstance(usage, dict)
        and "input_tokens" in usage
        and (not isinstance(usage.get("input_tokens_details"), dict)
             or "cached_tokens" not in usage["input_tokens_details"]
             or ("cache_write_tokens" not in usage["input_tokens_details"]
                 and rates is not None
                 and rates.get("cache_write_usd_per_million") != rates.get("input_usd_per_million")))
    ):
        return None
    if counts is None or rates is None or tool_calls is None or _usage_count(tool_calls) is None:
        return None
    inputs, outputs, cached, writes = counts
    portions = [
        (inputs - cached - writes, "input_usd_per_million"),
        (outputs, "output_usd_per_million"),
        (cached, "cached_input_usd_per_million"),
        (writes, "cache_write_usd_per_million"),
    ]
    if any(count and field not in rates for count, field in portions):
        return None
    if tool_calls and "web_search_usd_per_call" not in rates:
        return None
    cost = sum(count * rates.get(field, 0) / 1_000_000 for count, field in portions)
    cost += tool_calls * rates.get("web_search_usd_per_call", 0)
    return cost


def validate_cost_configuration(policy: StagePolicy, uses_tools: bool = False) -> None:
    """Reject an unenforceable requested cost ceiling before spending on an API call."""
    if policy.max_cost_usd is None:
        return
    configured = pricing().get(policy.model, {})
    needed = {
        "input_usd_per_million",
        "output_usd_per_million",
        "cached_input_usd_per_million",
        "cache_write_usd_per_million",
    }
    if policy.max_output_tokens == 0 and not uses_tools:
        needed = {"input_usd_per_million"}
    if uses_tools:
        needed.add("web_search_usd_per_call")
    if not needed <= configured.keys():
        raise BudgetExceeded("COST_BUDGET_UNVERIFIABLE")


def request_cost_ceiling(policy: StagePolicy, input_tokens: int, uses_tools=False) -> float | None:
    """Bound token charges at the largest configured input/cache rate.

    Tool counts are not bounded by this protocol, so a web tool estimate cannot
    be represented as an enforceable pre-call ceiling.
    """
    rates = pricing().get(policy.model, {})
    if policy.max_output_tokens == 0 and not uses_tools:
        rate = rates.get("input_usd_per_million")
        return None if rate is None else input_tokens * rate / 1000000
    inputs = {"input_usd_per_million", "cached_input_usd_per_million", "cache_write_usd_per_million"}
    if uses_tools or not (inputs | {"output_usd_per_million"}) <= rates.keys():
        return None
    return (input_tokens * max(rates[name] for name in inputs)
            + policy.max_output_tokens * rates["output_usd_per_million"]) / 1000000


def validate_request_cost(policy: StagePolicy, input_tokens: int, uses_tools=False) -> None:
    if policy.max_cost_usd is None:
        return
    ceiling = request_cost_ceiling(policy, input_tokens, uses_tools)
    if ceiling is None:
        raise BudgetExceeded("COST_BUDGET_UNVERIFIABLE")
    if ceiling > policy.max_cost_usd:
        raise BudgetExceeded("COST_BUDGET_EXCEEDED")


def validate_provider_configuration(default_model: str) -> None:
    configured = _object_setting("OPENAI_STAGE_POLICIES")
    for stage in configured:
        policy = stage_policy(stage, default_model)
        validate_cost_configuration(policy, uses_tools=stage == "web_search")
    pricing()


def evaluate_response(
    policy: StagePolicy,
    usage: dict[str, Any] | None,
    latency_ms: int,
    tool_calls: int | None = 0,
) -> dict[str, Any]:
    """Validate actual latency and usage before accepting a provider result into application state."""
    cost = estimated_cost(policy.model, usage, tool_calls)
    counts = token_totals(usage)
    if latency_ms > policy.timeout_seconds * 1000:
        raise BudgetExceeded("LATENCY_BUDGET_EXCEEDED")
    if counts and counts[1] > policy.max_output_tokens:
        raise BudgetExceeded("OUTPUT_TOKEN_BUDGET_EXCEEDED")
    if policy.max_input_tokens is not None:
        if counts is None:
            raise BudgetExceeded("TOKEN_BUDGET_UNVERIFIABLE")
        if counts[0] > policy.max_input_tokens:
            raise BudgetExceeded("INPUT_TOKEN_BUDGET_EXCEEDED")
    if policy.max_cost_usd is not None:
        if cost is None:
            raise BudgetExceeded("COST_BUDGET_UNVERIFIABLE")
        if cost > policy.max_cost_usd:
            raise BudgetExceeded("COST_BUDGET_EXCEEDED")
    return {"cost": cost, "budget_status": "WITHIN_CONFIGURED_LIMITS"}
