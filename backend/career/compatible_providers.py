"""Official HF/Groq chat adapters. No automatic paid fallback or fake output."""

import json
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, TypeVar

from openai import DefaultHttpxClient, OpenAI
from pydantic import BaseModel

from career.prompts import instructions_for
from career.provider_config import ProviderSettings
from career.provider_policy import StagePolicy, stage_policy
from career.providers import OpenAIProvider, ProviderUnavailable
from career.request_budget import bounded_policy

T = TypeVar("T", bound=BaseModel)
ENDPOINTS = {
    "huggingface": "https://router.huggingface.co/v1",
    "groq": "https://api.groq.com/openai/v1",
}


def _usage(response: Any) -> dict[str, Any] | None:
    value = getattr(response, "usage", None)
    if value is None:
        return None
    raw = value.model_dump() if hasattr(value, "model_dump") else value
    if not isinstance(raw, dict):
        return None
    details = raw.get("prompt_tokens_details") or {}
    return {
        "input_tokens": raw.get("prompt_tokens"),
        "output_tokens": raw.get("completion_tokens"),
        "total_tokens": raw.get("total_tokens"),
        "input_tokens_details": {"cached_tokens": details.get("cached_tokens", 0)} if isinstance(details, dict) else {},
    }


class CompatibleProvider(OpenAIProvider):
    """The shared observer is reused; the upstream protocol is Chat Completions."""

    def __init__(self, settings: ProviderSettings):
        if settings.provider not in ENDPOINTS or not settings.token or not settings.free_only_confirmed:
            raise ProviderUnavailable("무료 한도 계정과 AI 연결 설정을 확인해 주세요.")
        self.provider_name = "HuggingFace" if settings.provider == "huggingface" else "Groq"
        self.provider_id = settings.provider
        self.model = settings.model
        self.client = OpenAI(
            api_key=settings.token,
            base_url=ENDPOINTS[settings.provider],
            max_retries=0,
            timeout=60,
            http_client=DefaultHttpxClient(follow_redirects=False),
        )
        self.last_trace: dict[str, Any] = {}
        self.observed_retry_count = 0

    def _policy(self, stage: str) -> StagePolicy:
        policy = stage_policy(stage, self.model)
        # A bounded default avoids reserving 16K output against a small free-plan quota.
        output = min(policy.max_output_tokens, 4096)
        # The shared free Groq request budget is conservative; it is not a
        # statement about the account's live remaining tokens. HF also receives
        # a bounded byte estimate even when no stage override was configured.
        input_cap = 32768 if self.provider_id == "huggingface" else max(256, 8000 - output - 256)
        return replace(policy, max_output_tokens=output,
                       max_input_tokens=min(policy.max_input_tokens or input_cap, input_cap))

    def _call(self, policy: StagePolicy, messages: list[dict], response_format: dict | None):
        policy = bounded_policy(policy)
        arguments: dict[str, Any] = {
            "model": policy.model,
            "messages": messages,
            "max_tokens": policy.max_output_tokens,
            "timeout": policy.timeout_seconds,
            "stream": False,
        }
        if response_format is not None:
            arguments["response_format"] = response_format
        if self.provider_id == "groq" and policy.model.startswith("openai/gpt-oss-"):
            arguments["reasoning_effort"] = "low"
        raw = self.client.chat.completions.create(**arguments)
        # Never forward reasoning, raw errors or additional provider fields to telemetry.
        return SimpleNamespace(raw=raw, usage=_usage(raw))

    @staticmethod
    def _content(response: Any) -> str:
        choices = getattr(response.raw, "choices", [])
        if len(choices) != 1 or choices[0].finish_reason != "stop":
            raise ProviderUnavailable("AI 응답이 끝나지 않았습니다. 기존 문서는 유지됩니다.")
        message = choices[0].message
        content = getattr(message, "content", None)
        if getattr(message, "refusal", None) or getattr(message, "tool_calls", None):
            raise ProviderUnavailable("작성 결과를 확인하지 못했습니다.")
        if not isinstance(content, str) or not content.strip():
            raise ProviderUnavailable("AI 응답이 비어 있습니다.")
        return content

    def structured(
        self,
        prompt_id: str,
        context: dict[str, Any],
        schema: type[T],
        validate: Callable[[T], T] | None = None,
        operation: str = "structured",
    ) -> T:
        policy = self._policy(prompt_id)
        messages = [
            {"role": "system", "content": instructions_for(prompt_id)},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
        ]
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": schema.model_json_schema(),
                # Fireworks supports the full nested resume contract. Groq best-effort
                # accommodates dynamic mapping fields; local validation is mandatory.
                "strict": self.provider_id == "huggingface",
            },
        }

        def parsed(response) -> T:
            result = schema.model_validate_json(self._content(response))
            result = validate(result) if validate else result
            return result

        result = self._observe(
            prompt_id,
            operation,
            policy.model,
            {"messages": messages, "response_format": response_format, "model": policy.model},
            lambda: self._call(policy, messages, response_format),
            parsed,
            policy=policy,
        )
        return result

    def generate(self, prompt_id: str, context: dict[str, Any]) -> str:
        policy = self._policy(prompt_id)
        messages = [
            {"role": "system", "content": instructions_for(prompt_id)},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
        ]
        return self._observe(
            prompt_id,
            "generate",
            policy.model,
            {"messages": messages, "model": policy.model},
            lambda: self._call(policy, messages, None),
            self._content,
            policy=policy,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        # No implicit commercial embedding calls while a free provider is selected.
        raise ProviderUnavailable("선택한 무료 제공자의 임베딩은 설정되지 않았습니다. 키워드 검색을 사용해 주세요.")
