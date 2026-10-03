import json

import httpx2 as httpx
import pytest
from career.models import Artifact
from career.provider_policy import BudgetExceeded, StagePolicy, estimated_input_tokens, validate_request_input
from career.providers import ProviderUnavailable
from career.request_budget import bounded_policy, deadline_scope
from test_compatible_providers import Output, client, result


def test_one_deadline_is_shared_by_sequential_stages_and_http_timeout(monkeypatch):
    import career.request_budget as budget

    clock = [100.0]
    monkeypatch.setattr(budget, "monotonic", lambda: clock[0])
    with deadline_scope(100):
        assert bounded_policy(StagePolicy("model", timeout_seconds=60)).timeout_seconds == 60
        clock[0] = 175.0
        assert bounded_policy(StagePolicy("model", timeout_seconds=60)).timeout_seconds == 25
        with deadline_scope(100):
            assert bounded_policy(StagePolicy("model", timeout_seconds=60)).timeout_seconds == 25
        clock[0] = 201.0
        with pytest.raises(BudgetExceeded) as failure:
            bounded_policy(StagePolicy("model"))
        assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"


def test_korean_system_json_and_actual_schema_are_counted_before_http():
    data = {"messages": [{"role": "system", "content": "사실성 유지"},
                         {"role": "user", "content": "한국어 근거"}],
            "response_format": {"json_schema": Output.model_json_schema()}}
    estimate = estimated_input_tokens(data)
    assert estimate > len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    with pytest.raises(BudgetExceeded):
        validate_request_input(StagePolicy("model", max_input_tokens=100), data)
    calls = []
    instance = client(lambda request: (calls.append(request), httpx.Response(200, json=result({"message": "ok"})))[1])
    with pytest.raises(ProviderUnavailable, match="입력 한도"):
        instance.structured("writer", {"evidence": "한국어" * 15000}, Output)
    assert calls == []
    assert instance.last_trace["error_code"] == "INPUT_TOKEN_BUDGET_EXCEEDED"
    instance.client.close()


def test_late_success_is_discarded_and_shared_timeout_reaches_transport(monkeypatch):
    import career.request_budget as budget

    clock = [100.0]
    monkeypatch.setattr(budget, "monotonic", lambda: clock[0])
    calls = []

    def handle(request):
        calls.append(request)
        assert request.extensions["timeout"]["read"] <= 5
        clock[0] = 106.0
        return httpx.Response(200, json=result({"message": "late"}))

    instance = client(handle)
    with deadline_scope(5), pytest.raises(ProviderUnavailable, match="전체 AI 처리 시간"):
        instance.structured("writer", {}, Output)
    assert len(calls) == 1 and instance.last_trace["status"] == "FAILED"
    instance.client.close()


def test_transport_that_ignores_socket_timeout_cannot_hold_the_request():
    from threading import Event
    from time import monotonic

    from career.request_budget import call_with_deadline

    blocked, release = Event(), Event()

    def transport():
        blocked.set()
        release.wait(2)
        return "late result"

    started = monotonic()
    try:
        with deadline_scope(0.03), pytest.raises(BudgetExceeded) as failure:
            call_with_deadline(transport, StagePolicy("model"))
        assert blocked.is_set() and monotonic() - started < 0.5
        assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"
    finally:
        release.set()


def test_router_uses_latest_identity_and_state_preserves_full_selected_proof():
    from career.conversation import planner_artifacts

    items = [Artifact(id="old", kind="Draft", slot="q", version=1, status="ACTIVE", data={"text": "old"}),
             Artifact(id="latest", kind="Draft", slot="q", version=2, status="STALE", data={"text": "private" * 10000}),
             Artifact(id="brief", kind="QuestionBrief", slot="q", version=1, status="LOCKED", data={})]
    summaries = planner_artifacts(items, items[1])
    assert {item["id"] for item in summaries} == {"latest", "brief"}
    assert next(item for item in summaries if item["id"] == "latest")["status"] == "STALE"
    assert "private" not in json.dumps(summaries)
    assert items[1].data["text"] == "private" * 10000


def test_manual_conversation_guard_distinguishes_freeze_that_runs_ai_qa():
    from career.conversation import ChatRequest, conversation_uses_ai

    for text in ["현재 상태", "도움말", "문항 추가: 질문", "이걸로 가자", "제출했다", "RAG 빼"]:
        assert not conversation_uses_ai(ChatRequest(text=text, client_id="fixture-id"))
    assert not conversation_uses_ai("잠가", "WAITING_STRATEGY_APPROVAL")
    assert not conversation_uses_ai("잠가", "READY_TO_FREEZE", "ResumeContent")
    assert conversation_uses_ai("잠가", "READY_TO_FREEZE")
    assert conversation_uses_ai("이 문장 고쳐줘")


def test_configured_cost_ceiling_checks_worst_output_before_http(monkeypatch):
    model = "openai/gpt-oss-120b:fireworks-ai"
    monkeypatch.setenv("CAREER_LLM_STAGE_POLICIES", json.dumps({"writer": {"max_cost_usd": 0.00001}}))
    monkeypatch.setenv("CAREER_LLM_PRICING_JSON", json.dumps({model: {
        "input_usd_per_million": 2, "cached_input_usd_per_million": 1,
        "cache_write_usd_per_million": 3, "output_usd_per_million": 4}}))
    calls = []
    instance = client(lambda request: calls.append(request))
    with pytest.raises(ProviderUnavailable):
        instance.structured("writer", {}, Output)
    assert calls == [] and instance.last_trace["error_code"] == "COST_BUDGET_EXCEEDED"
    assert instance.last_trace["usage"] is None
    instance.client.close()


def test_embedding_cost_ceiling_does_not_reserve_generated_text(monkeypatch):
    from career.provider_policy import request_cost_ceiling, validate_cost_configuration

    monkeypatch.setenv("CAREER_LLM_PRICING_JSON", json.dumps({"embedding-model": {"input_usd_per_million": 0.1}}))
    policy = StagePolicy("embedding-model", max_output_tokens=0, max_cost_usd=0.01)
    validate_cost_configuration(policy)
    assert request_cost_ceiling(policy, 1000) == pytest.approx(0.0001)


def test_deadline_cannot_commit_a_late_artifact(db, monkeypatch):
    import career.request_budget as budget
    from career.activity import run_operation
    from career.workflow import Workflow
    from sqlalchemy import select

    ws = Workflow(db, "owner").create("synthetic", "role", "JD")
    db.commit()
    clock = [100.0]
    monkeypatch.setattr(budget, "monotonic", lambda: clock[0])

    def operation():
        db.add(Artifact(user_id="owner", workspace_id=ws.id, kind="Review", data={"approved": True}))
        db.flush()
        clock[0] = 201.0
        return {}

    with pytest.raises(ProviderUnavailable, match="미완료 결과"):
        run_operation(db, "owner", ws.id, "review", operation)
    assert list(db.scalars(select(Artifact))) == []
