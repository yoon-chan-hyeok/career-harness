import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextvars import copy_context
from typing import Any, Protocol

import httpx
from pydantic import BaseModel
from sqlalchemy.orm import Session

from career.models import PromptRun
from career.providers import LLMProvider, OpenAIProvider, ProviderUnavailable
from career.runtime_trace import emit_trace, input_hash, numeric_confidence, numeric_metadata, trace_sink

TASKS = {"question_type", "role_noun_alignment", "direct_answer", "jargon_overload", "revision_routing"}


class Decision(BaseModel):
    choice: str
    confidence: str
    rationale: str


class DecisionModel(Protocol):
    def choose(self, task_id: str, state: dict, options: list[str]) -> Decision: ...
    def binary(self, task_id: str, state: dict) -> bool: ...
    def score(self, task_id: str, state: dict, scale: list[str]) -> str: ...


class LLMStructuredDecisionProvider:
    trace_emitting = True

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def choose(self, task_id: str, state: dict, options: list[str]) -> Decision:
        context = {"state": state, "options": options}

        def valid(result: Decision) -> Decision:
            if result.choice not in options:
                raise ValueError("Decision is outside allowed options")
            return result

        if isinstance(self.provider, OpenAIProvider):
            return self.provider.structured(
                task_id, context, Decision, validate=valid, operation="bounded_decision"
            )
        if getattr(self.provider, "trace_emitting", False):
            return valid(self.provider.structured(task_id, context, Decision))
        start = time.monotonic()
        trace: dict[str, Any] = {
            "operation": "bounded_decision",
            "task": task_id,
            "input_hash": input_hash(context),
            "status": "RUNNING",
            "retry_count": None,
            "cost": None,
            "usage": None,
        }
        try:
            result = valid(self.provider.structured(task_id, context, Decision))
            trace["status"] = "COMPLETED"
            return result
        except Exception:
            trace.update({"status": "FAILED", "error_code": "BOUNDED_DECISION_FAILED"})
            raise
        finally:
            previous = getattr(self.provider, "last_trace", {})
            for key in ("model", "usage", "cost"):
                if key in previous:
                    trace[key] = previous[key]
            trace["latency_ms"] = round((time.monotonic() - start) * 1000)
            emit_trace(task_id, type(self.provider).__name__, trace)

    def binary(self, task_id: str, state: dict) -> bool:
        return self.choose(task_id, state, ["yes", "no"]).choice == "yes"

    def score(self, task_id: str, state: dict, scale: list[str]) -> str:
        return self.choose(task_id, state, scale).choice


class JevDecisionProvider:
    """Official HTTP choice adapter with an injectable transport for deterministic tests."""

    trace_emitting = True

    def __init__(self, transport=None):
        self.transport = transport or (self.http_transport if os.getenv("JEV_API_KEY") else None)
        self.last_trace: dict[str, Any] = {}

    def http_transport(self, task_id: str, state: dict, options: list[str]):
        # Fixed official endpoint; credentials never follow a redirect to another host.
        with httpx.Client(timeout=2.0, follow_redirects=False) as client:
            response = client.post(
                "https://api.typesafe.ai/v1/systemone",
                headers={"Authorization": "Bearer " + os.environ["JEV_API_KEY"]},
                json={
                    "model": os.getenv("JEV_MODEL", "jev-latest"),
                    "state": json.dumps(state, ensure_ascii=False),
                    "questions": {
                        "decision": {
                            "type": "choice",
                            "instructions": "Evaluate only this bounded task: " + task_id,
                            "criteria": {option: option for option in options},
                        }
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()
        answer = payload["answers"]["decision"]
        confidence = numeric_confidence(answer.get("confidence"))
        self.last_trace = {
            "usage": numeric_metadata(payload.get("usage")),
            "model": payload.get("model"),
            "confidence": confidence,
            "cost": numeric_metadata(payload.get("cost")),
        }
        return {
            "choice": answer["choice"],
            "confidence": str(confidence),
            "rationale": "TypeSafe choice probability; no generated explanation",
        }

    def choose(self, task_id: str, state: dict, options: list[str]) -> Decision:
        if task_id not in TASKS:
            raise ValueError("Jev task is not allowlisted")
        start = time.monotonic()
        trace: dict[str, Any] = {
            "operation": "bounded_decision",
            "task": task_id,
            "mode": "SHADOW_ONLY",
            "input_hash": input_hash({"task": task_id, "state": state, "options": options}),
            "model": os.getenv("JEV_MODEL", "jev-latest"),
            "usage": None,
            "cost": None,
            "confidence": None,
            "retry_count": None,
            "status": "RUNNING",
        }
        self.last_trace = {}
        try:
            if self.transport is None:
                raise ProviderUnavailable("Jev transport is not configured")
            response = self.transport(task_id, state, options)
            confidence = numeric_confidence(response.get("confidence"))
            if confidence is None:
                raise ProviderUnavailable("Invalid shadow confidence")
            result = Decision.model_validate({**response, "confidence": str(confidence)})
            if result.choice not in options:
                raise ProviderUnavailable("Invalid shadow decision")
            trace["status"] = "COMPLETED"
            trace["confidence"] = confidence
            return result
        except Exception as error:
            code = (
                "PROVIDER_TIMEOUT" if isinstance(error, httpx.TimeoutException)
                else "PROVIDER_HTTP_FAILED" if isinstance(error, httpx.HTTPStatusError)
                else "PROVIDER_CONNECTION_FAILED" if isinstance(error, httpx.NetworkError)
                else "PROVIDER_NOT_CONFIGURED" if self.transport is None
                else "PROVIDER_CALL_FAILED"
            )
            trace.update({"status": "FAILED", "error_code": code})
            raise ProviderUnavailable(
                "Jev 판단 응답을 확인하지 못했습니다. 주 모델의 판단은 그대로 유지됩니다."
            ) from None
        finally:
            for key in ("model", "usage", "cost"):
                if self.last_trace.get(key) is not None:
                    trace[key] = self.last_trace[key]
            trace["latency_ms"] = round((time.monotonic() - start) * 1000)
            self.last_trace = trace
            emit_trace(task_id, "Jev", trace)

    def binary(self, task_id: str, state: dict) -> bool:
        return self.choose(task_id, state, ["yes", "no"]).choice == "yes"

    def score(self, task_id: str, state: dict, scale: list[str]) -> str:
        return self.choose(task_id, state, scale).choice


def shadow_decision(
    db: Session,
    user: str,
    primary: DecisionModel,
    shadow: DecisionModel,
    task_id: str,
    state: dict,
    options: list[str],
    timeout=2.0,
) -> Decision:
    if task_id not in TASKS:
        raise ValueError("Task is not safe for shadow evaluation")
    executor = ThreadPoolExecutor(max_workers=1)
    start = time.monotonic()
    collected: list[tuple[str, str, dict[str, Any]]] = []
    worker_context = copy_context()

    def choose_shadow():
        token = trace_sink.set(lambda stage, provider, data: collected.append((stage, provider, data)))
        try:
            return shadow.choose(task_id, state, options)
        finally:
            trace_sink.reset(token)

    future = executor.submit(worker_context.run, choose_shadow)
    trace: dict[str, Any] = {
        "task": task_id,
        "cost": None,
        "mode": "SHADOW_ONLY",
        "input_hash": input_hash({"task": task_id, "state": state, "options": options}),
        "status": "RUNNING",
        "primary_confidence": None,
        "shadow_confidence": None,
    }
    try:
        result = primary.choose(task_id, state, options)
        trace["primary_hash"] = input_hash(result.model_dump())
        trace["primary_confidence"] = numeric_confidence(result.confidence)
        try:
            candidate = future.result(timeout=timeout)
            trace.update(
                {
                    "shadow_hash": input_hash(candidate.model_dump()),
                    "disagreement": candidate.choice != result.choice,
                    "shadow_confidence": numeric_confidence(candidate.confidence),
                }
            )
            trace["status"] = "COMPLETED"
        except (Exception, TimeoutError) as error:
            trace["error_type"] = type(error).__name__
            trace["status"] = "FAILED"
            if isinstance(error, TimeoutError):
                trace["error_code"] = "SHADOW_TIMEOUT"
        return result
    except Exception as error:
        trace.update({"status": "FAILED", "error_type": type(error).__name__})
        raise
    finally:
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        trace["latency_ms"] = round((time.monotonic() - start) * 1000)
        for stage, provider, metadata in list(collected):
            emit_trace(stage, provider, metadata)
        if not collected and trace.get("error_code") == "SHADOW_TIMEOUT":
            emit_trace(task_id, "Jev", {
                "operation": "bounded_decision", "mode": "SHADOW_ONLY", "task": task_id,
                "input_hash": trace["input_hash"], "latency_ms": trace["latency_ms"],
                "status": "FAILED", "error_code": "SHADOW_TIMEOUT", "usage": None,
                "cost": None, "retry_count": None, "confidence": None,
            })
        trace["provider_usage"] = {
            key: value for key, value in getattr(shadow, "last_trace", {}).items()
            if key in {"model", "usage", "cost", "latency_ms", "status", "error_code", "input_hash", "retry_count"}
        }
        trace["provider_usage"]["confidence"] = numeric_confidence(
            getattr(shadow, "last_trace", {}).get("confidence")
        )
        db.add(PromptRun(user_id=user, stage="shadow_decision", provider="Jev", data=trace))
