import os
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any, Protocol, TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel

from career.cache_metrics import cache_observation
from career.prompt_cache import prepare
from career.prompts import COMMON_SYSTEM, instructions_for, prompt_version
from career.provider_policy import (
    BudgetExceeded,
    StagePolicy,
    estimated_cost,
    evaluate_response,
    stage_policy,
    validate_cost_configuration,
    validate_request_cost,
    validate_request_input,
)
from career.request_budget import bounded_policy, call_with_deadline, check_deadline
from career.runtime_trace import emit_trace, input_hash, numeric_metadata
from career.schemas import ResearchResult

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")
SYSTEM = COMMON_SYSTEM


class ProviderUnavailable(RuntimeError):
    pass


def provider_error_code(error: Exception) -> str:
    if isinstance(error, BudgetExceeded):
        return error.code
    if isinstance(error, APITimeoutError):
        return "PROVIDER_TIMEOUT"
    if isinstance(error, AuthenticationError):
        return "PROVIDER_AUTHENTICATION_FAILED"
    if isinstance(error, RateLimitError):
        return "PROVIDER_RATE_LIMITED"
    if isinstance(error, APIConnectionError):
        return "PROVIDER_CONNECTION_FAILED"
    if isinstance(error, APIStatusError):
        if error.status_code == 402:
            return "PROVIDER_CREDIT_EXHAUSTED"
        return "PROVIDER_HTTP_FAILED"
    return "PROVIDER_RESPONSE_INVALID" if isinstance(error, ProviderUnavailable) else "PROVIDER_CALL_FAILED"


class LLMProvider(Protocol):
    def structured(self, prompt_id: str, context: dict[str, Any], schema: type[T]) -> T: ...
    def generate(self, prompt_id: str, context: dict[str, Any]) -> str: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIProvider:
    def _validate_input(self, policy: StagePolicy, request_data: dict[str, Any]) -> int:
        return validate_request_input(policy, request_data)

    trace_emitting = True
    provider_name = "OpenAI"

    def __init__(self):
        self.model = os.getenv("OPENAI_MODEL", "")
        if not os.getenv("OPENAI_API_KEY") or not self.model:
            raise ProviderUnavailable(
                "OPENAI_API_KEY와 OPENAI_MODEL 설정이 필요합니다. 수동 입력은 계속 사용할 수 있습니다."
            )
        self.client = OpenAI(timeout=60, max_retries=0)
        self.observed_retry_count = 0
        self.last_trace: dict[str, Any] = {}

    def _observe(
        self,
        stage: str,
        operation: str,
        model: str,
        request_data: dict[str, Any],
        call: Callable[[], Any],
        read: Callable[[Any], R],
        policy: StagePolicy | None = None,
        count_tools: Callable[[Any], int | None] | None = None,
        cache_metadata: dict[str, str] | None = None,
    ) -> R:
        start = time.monotonic()
        trace: dict[str, Any] = {
            "prompt_template_version": prompt_version(stage),
            "model": model,
            "operation": operation,
            "input_hash": input_hash(request_data),
            "usage": None,
            "cost": None,
            "retry_count": getattr(self, "observed_retry_count", None),
            "status": "RUNNING",
        }
        trace.update(cache_metadata or {})
        response = None
        envelope = ticket = None
        try:
            policy = bounded_policy(policy or stage_policy(stage, model))
            trace.update({"timeout_seconds": policy.timeout_seconds, "max_output_tokens": policy.max_output_tokens,
                          "max_input_tokens": policy.max_input_tokens, "max_cost_usd": policy.max_cost_usd})
            validate_cost_configuration(policy, uses_tools=count_tools is not None)
            input_estimate = self._validate_input(policy, request_data)
            validate_request_cost(policy, input_estimate, uses_tools=count_tools is not None)
            from career.usage_limits import usage_envelope

            envelope = usage_envelope.get()
            if envelope is not None:
                ticket = envelope.draw(policy, input_estimate, uses_tools=count_tools is not None)
            response = call_with_deadline(call, policy)
            check_deadline()
            usage = getattr(response, "usage", None)
            trace["usage"] = numeric_metadata(usage.model_dump() if usage is not None and hasattr(usage, "model_dump") else usage)
            tools = count_tools(response) if count_tools else 0
            trace["tool_calls"] = tools
            trace["latency_ms"] = round((time.monotonic() - start) * 1000)
            trace["cost"] = estimated_cost(model, trace["usage"], tools)
            trace["cost_basis"] = "CONFIGURED_RATE_FINAL_RESPONSE_ESTIMATE" if trace["cost"] is not None else None
            trace.update(evaluate_response(policy, trace["usage"], trace["latency_ms"], tools))
            result = read(response)
            check_deadline()
            trace["output_hash"] = input_hash(result.model_dump() if isinstance(result, BaseModel) else result)
            trace["status"] = "COMPLETED"
            return result
        except Exception as error:
            trace.update({"status": "FAILED", "error_code": provider_error_code(error)})
            if isinstance(error, BudgetExceeded):
                trace["budget_status"] = "UNVERIFIABLE" if error.code.endswith("UNVERIFIABLE") else "LIMIT_EXCEEDED"
                raise ProviderUnavailable(str(error)) from None
            if isinstance(error, RateLimitError) or (isinstance(error, APIStatusError) and error.status_code == 402):
                raise ProviderUnavailable(
                    "AI 제공자의 무료 한도 또는 크레딧을 확인해 주세요. 잠시 후 재시도하거나 직접 작성할 수 있습니다. 유료 제공자로 자동 전환하지 않습니다."
                ) from None
            raise ProviderUnavailable(
                "AI 제공자의 응답을 처리하지 못했습니다. 기존 자료는 유지됩니다. 연결 설정을 확인하거나 다시 시도해 주세요."
            ) from None
        finally:
            usage = getattr(response, "usage", None)
            raw_usage = usage.model_dump() if usage is not None and hasattr(usage, "model_dump") else usage
            if usage is not None:
                trace["usage"] = numeric_metadata(raw_usage)
            if operation != "embed":
                observation = cache_observation(raw_usage)
                trace.update({"cache_status": observation["status"],
                              "cache_input_tokens": observation["input_tokens"],
                              "cached_input_tokens": observation["cached_tokens"],
                              "cache_write_tokens": observation["cache_write_tokens"],
                              "cache_hit_ratio": observation["hit_ratio"]})
            if envelope is not None and ticket is not None:
                envelope.settle_call(ticket, model, trace.get("usage"),
                                     trace.get("tool_calls", None if count_tools is not None else 0))
            trace["latency_ms"] = round((time.monotonic() - start) * 1000)
            self.last_trace = trace
            emit_trace(stage, self.provider_name, trace)

    def structured(
        self,
        prompt_id: str,
        context: dict[str, Any],
        schema: type[T],
        validate: Callable[[T], T] | None = None,
        operation: str = "structured",
    ) -> T:
        policy = stage_policy(prompt_id, self.model)
        schema_data = schema.model_json_schema()
        prompt = prepare(prompt_id, context, instructions_for(prompt_id), policy.model, "openai", schema_data)
        cache_arguments: dict[str, Any] = {"prompt_cache_key": prompt.key} if prompt.key else {}
        request_data = {
            "model": policy.model,
            "instructions": prompt.instructions,
            "input": prompt.content,
            "schema": schema_data,
            **cache_arguments,
        }

        def parsed(response) -> T:
            if getattr(response, "status", "completed") != "completed" or response.output_parsed is None:
                raise ProviderUnavailable("모델 응답을 검증하지 못했습니다.")
            result = schema.model_validate(response.output_parsed)
            return validate(result) if validate else result

        return self._observe(
            prompt_id,
            operation,
            policy.model,
            request_data,
            lambda: self.client.responses.parse(
                model=policy.model,
                instructions=request_data["instructions"],
                input=request_data["input"],
                text_format=schema,
                store=False,
                timeout=bounded_policy(policy).timeout_seconds,
                max_output_tokens=policy.max_output_tokens,
                **cache_arguments,
            ),
            parsed,
            policy=policy,
            cache_metadata={"prompt_cache_scope": prompt.scope, "prompt_cache_layout_version": prompt.layout_version},
        )

    def generate(self, prompt_id: str, context: dict[str, Any]) -> str:
        policy = stage_policy(prompt_id, self.model)
        prompt = prepare(prompt_id, context, instructions_for(prompt_id), policy.model, "openai")
        cache_arguments: dict[str, Any] = {"prompt_cache_key": prompt.key} if prompt.key else {}
        request_data = {
            "model": policy.model,
            "instructions": prompt.instructions,
            "input": prompt.content,
            **cache_arguments,
        }

        def text(response) -> str:
            if getattr(response, "status", "completed") != "completed" or not response.output_text:
                raise ProviderUnavailable("모델의 텍스트 응답이 완료되지 않았습니다.")
            return response.output_text

        return self._observe(
            prompt_id,
            "generate",
            policy.model,
            request_data,
            lambda: self.client.responses.create(
                model=policy.model, instructions=request_data["instructions"], input=request_data["input"], store=False,
                timeout=bounded_policy(policy).timeout_seconds, max_output_tokens=policy.max_output_tokens,
                **cache_arguments,
            ),
            text,
            policy=policy,
            cache_metadata={"prompt_cache_scope": prompt.scope, "prompt_cache_layout_version": prompt.layout_version},
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        policy = replace(stage_policy("embedding", model), model=model, max_output_tokens=0)
        request_data = {"model": model, "input": texts, "dimensions": 1536}

        def vectors(response) -> list[list[float]]:
            if len(response.data) != len(texts):
                raise ProviderUnavailable("임베딩 응답의 항목 수를 확인할 수 없습니다.")
            return [item.embedding for item in response.data]

        return self._observe(
            "embedding",
            "embed",
            model,
            request_data,
            lambda: self.client.embeddings.create(model=model, input=texts, dimensions=1536, timeout=bounded_policy(policy).timeout_seconds),
            vectors,
            policy=policy,
        )


class FakeLLMProvider:
    """Explicit injected fixtures only. Never selected automatically in the product."""

    def __init__(self, fixtures: dict[str, Any]):
        self.fixtures = fixtures
        self.last_trace = {"model": "fake-test-only", "cost": 0}

    def structured(self, prompt_id: str, context: dict[str, Any], schema: type[T]) -> T:
        return schema.model_validate(self.fixtures[prompt_id])

    def generate(self, prompt_id: str, context: dict[str, Any]) -> str:
        return str(self.fixtures[prompt_id])

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise ProviderUnavailable("Inject an explicit test embedder; no fake semantic vectors.")


class CompanyResearchProvider(Protocol):
    def research(self, company: str, role: str, jd_input: str) -> ResearchResult: ...


class ManualResearchProvider:
    def research(self, company: str, role: str, jd_input: str) -> ResearchResult:
        return ResearchResult(
            official_facts=[],
            external_evidence=[],
            role_signals=[],
            historical_jd_signals=[],
            selection_process_signals=[],
            inferences=[],
            sources=[],
        )


class FakeResearchProvider(ManualResearchProvider):
    """Explicit deterministic source fixtures; never selected by product configuration."""

    def __init__(self, fixture: dict[str, Any] | None = None):
        self.fixture = fixture

    def research(self, company: str, role: str, jd_input: str) -> ResearchResult:
        if self.fixture is None:
            return super().research(company, role, jd_input)
        return ResearchResult.model_validate(self.fixture)


class OpenAIWebResearchProvider:
    trace_emitting = True

    def __init__(self, llm: OpenAIProvider):
        self.llm = llm

    def research(self, company: str, role: str, jd_input: str) -> ResearchResult:
        policy = stage_policy("web_search", self.llm.model)
        prompt = prepare("web_search", {"company": company, "role": role, "jd_untrusted": jd_input},
                         instructions_for("web_search"), policy.model, "openai", {"tools": [{"type": "web_search"}]})
        cache_arguments: dict[str, Any] = {"prompt_cache_key": prompt.key} if prompt.key else {}
        request_data = {
            "model": policy.model,
            "instructions": prompt.instructions,
            "input": prompt.content,
            **cache_arguments,
        }
        def searched(response):
            if getattr(response, "status", "completed") != "completed" or not response.output_text:
                raise ProviderUnavailable("검색 응답이 완료되지 않았습니다.")
            return response

        def tools(response) -> int | None:
            outputs = getattr(response, "output", None)
            if not isinstance(outputs, list):
                return None
            return sum(getattr(item, "type", None) == "web_search_call" for item in outputs)

        response = self.llm._observe(
            "web_search",
            "web_search",
            policy.model,
            request_data,
            lambda: self.llm.client.responses.create(
                model=policy.model, instructions=request_data["instructions"], input=request_data["input"],
                tools=[{"type": "web_search"}], store=False,
                timeout=bounded_policy(policy).timeout_seconds, max_output_tokens=policy.max_output_tokens,
                **cache_arguments,
            ),
            searched,
            policy=policy,
            count_tools=tools,
            cache_metadata={"prompt_cache_scope": prompt.scope, "prompt_cache_layout_version": prompt.layout_version},
        )
        citations = []
        for output in response.output:
            if output.type == "message":
                for content in output.content:
                    if content.type == "output_text":
                        citations.extend(a.url for a in content.annotations if a.type == "url_citation")
        def verified(result: ResearchResult) -> ResearchResult:
            if any(s.url not in citations for s in result.sources):
                raise ProviderUnavailable("검색으로 확인되지 않은 출처가 포함되어 수동 모드로 돌아갑니다.")
            ids = {s.id for s in result.sources}
            if any(f.source_id not in ids for f in result.official_facts + result.external_evidence):
                raise ProviderUnavailable("회사 사실의 출처를 확인할 수 없습니다.")
            return result

        return self.llm.structured(
            "research_extract",
            {"untrusted_research": response.output_text, "allowed_urls": citations},
            ResearchResult,
            validate=verified,
        )


def configured_provider() -> LLMProvider:
    """Select one explicitly configured provider; never switch to a paid fallback."""
    from career.provider_config import provider_available, provider_settings

    settings = provider_settings()
    if not provider_available():
        raise ProviderUnavailable("설정에서 AI 제공자와 토큰, 무료 한도 설정을 확인해 주세요. 직접 작성은 계속 사용할 수 있습니다.")
    if settings.provider == "openai":
        return OpenAIProvider()
    from career.compatible_providers import CompatibleProvider

    return CompatibleProvider(settings)
