"""Regression coverage for safe, durable Jev probabilities without live providers."""

import json
from contextlib import contextmanager

import httpx
import pytest
from career.decisions import JevDecisionProvider, LLMStructuredDecisionProvider, shadow_decision
from career.models import PromptRun
from career.providers import FakeLLMProvider
from career.runtime_trace import emit_trace, trace_sink
from sqlalchemy import select

PRIVATE = "private provider prose and fixture credential must never be recorded"


@contextmanager
def capture_trace():
    rows = []
    token = trace_sink.set(lambda stage, provider, data: rows.append((stage, provider, data)))
    try:
        yield rows
    finally:
        trace_sink.reset(token)


def primary(confidence="HIGH"):
    return LLMStructuredDecisionProvider(
        FakeLLMProvider(
            {"direct_answer": {"choice": "yes", "confidence": confidence, "rationale": PRIVATE}}
        )
    )


def test_http_probability_reaches_durable_shadow_record_without_raw_provider_data(db, monkeypatch):
    original = httpx.Client
    monkeypatch.setenv("JEV_API_KEY", PRIVATE)
    monkeypatch.setenv("JEV_MODEL", "fixture-jev")

    def respond(request):
        assert request.headers["Authorization"] == "Bearer " + PRIVATE
        return httpx.Response(
            200,
            json={
                "model": "fixture-jev",
                "answers": {"decision": {"choice": "no", "confidence": 0.9, "explanation": PRIVATE}},
                "usage": {"input_tokens": 5, "text": PRIVATE},
                "raw_response": PRIVATE,
            },
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    shadow = JevDecisionProvider()
    with capture_trace() as rows:
        result = shadow_decision(db, "fixture", primary("0.82"), shadow, "direct_answer", {}, ["yes", "no"])
    assert result.choice == "yes"
    observed = next(data for _stage, provider, data in rows if provider == "Jev")
    assert observed["confidence"] == 0.9
    assert shadow.last_trace["confidence"] == 0.9
    db.commit()
    db.expunge_all()
    diagnostics = db.scalar(select(PromptRun).where(PromptRun.stage == "shadow_decision")).data
    assert diagnostics["primary_confidence"] == 0.82
    assert diagnostics["shadow_confidence"] == 0.9
    assert diagnostics["provider_usage"]["confidence"] == 0.9
    assert diagnostics["disagreement"] is True
    assert PRIVATE not in json.dumps(rows, allow_nan=False)
    assert PRIVATE not in json.dumps(diagnostics, allow_nan=False)


@pytest.mark.parametrize(
    "confidence", [None, True, "NaN", float("nan"), float("inf"), -0.01, 1.01, PRIVATE, {"text": PRIVATE}]
)
def test_invalid_jev_probability_is_unknown_and_cannot_change_primary(db, confidence):
    shadow = JevDecisionProvider(
        transport=lambda *_args: {"choice": "no", "confidence": confidence, "rationale": PRIVATE}
    )
    with capture_trace() as rows:
        result = shadow_decision(db, "fixture", primary(), shadow, "direct_answer", {}, ["yes", "no"])
    assert result.choice == "yes"
    assert shadow.last_trace["status"] == "FAILED"
    assert shadow.last_trace["confidence"] is None
    observed = next(data for _stage, provider, data in rows if provider == "Jev")
    assert observed["confidence"] is None
    db.flush()
    diagnostics = db.scalar(select(PromptRun).where(PromptRun.stage == "shadow_decision")).data
    assert diagnostics["status"] == "FAILED"
    assert diagnostics["primary_confidence"] is None
    assert diagnostics["shadow_confidence"] is None
    assert diagnostics["provider_usage"]["confidence"] is None
    assert PRIVATE not in json.dumps(rows, allow_nan=False)
    assert PRIVATE not in json.dumps(diagnostics, allow_nan=False)


@pytest.mark.parametrize("confidence, expected", [(0, 0.0), (1, 1.0), ("0.9", 0.9), (PRIVATE, None), (True, None), (float("nan"), None), (2, None)])
def test_trace_boundary_rejects_probability_prose_nonfinite_and_invalid_ranges(confidence, expected):
    with capture_trace() as rows:
        emit_trace("direct_answer", "Jev", {"confidence": confidence})
    assert rows[0][2]["confidence"] == expected
    assert PRIVATE not in json.dumps(rows, allow_nan=False)
