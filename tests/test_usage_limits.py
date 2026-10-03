# ruff: noqa: F811 -- reusable API fixture and transport factory
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from career.db import Base, Record
from career.provider_policy import BudgetExceeded, StagePolicy
from career.usage_limits import configure_usage, request_budget_scope, usage_status, validate_limits
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool
from test_api import client  # noqa: F401 -- reusable authenticated API fixture


def ledger(tmp_path):
    # Same constraint as serverless: one connection, no overflow. File-backed
    # SQLite also catches writes retained during multiple provider calls.
    engine = create_engine("sqlite:///" + str(tmp_path / "ledger.db"),
                           connect_args={"check_same_thread": False},
                           poolclass=QueuePool, pool_size=1, max_overflow=0, pool_timeout=1)
    Base.metadata.create_all(engine)
    return engine


def test_calls_settle_after_business_connection_release_and_survive_rollback(tmp_path):
    engine = ledger(tmp_path)
    with Session(engine) as db:
        with request_budget_scope(db, "owner", "conversation") as quota:
            first = quota.draw(StagePolicy("no-rate", max_output_tokens=100), 300)
            quota.settle_call(first, "no-rate", {"input_tokens": 50, "output_tokens": 20, "input_tokens_details": {}})
            db.add(Record(user_id="owner", kind="temporary", data={}))
            db.flush()  # Retains the SQLite writer lock and sole pool connection.
            second = quota.draw(StagePolicy("no-rate", max_output_tokens=100), 200)
            # A timeout has no usage; reserve all 300 tokens for this call.
            quota.settle_call(second, "no-rate", None)
        db.rollback()
    with Session(engine) as db:
        result = usage_status(db, "owner")
        assert result["daily"]["calls"] == 2
        assert result["daily"]["tokens"] == 370
        assert result["daily"]["reserved_calls"] == 0
        assert result["daily"]["reserved_tokens"] == 0
        assert result["daily"]["estimated_cost_usd"] is None
        assert result["daily"]["unknown_cost_calls"] == 2
        assert usage_status(db, "other")["daily"]["calls"] == 0
    engine.dispose()


def test_concurrent_request_and_parallel_calls_cannot_exceed_limits(tmp_path):
    engine = ledger(tmp_path)
    with Session(engine) as db:
        configure_usage(db, "owner", {"daily_calls": 1})
        db.commit()
    started = Barrier(2)

    def first_request():
        with Session(engine) as db, request_budget_scope(db, "owner", "review") as quota:
            started.wait(timeout=5)
            started.wait(timeout=5)
            with ThreadPoolExecutor(max_workers=2) as workers:
                def call(_):
                    try:
                        quota.draw(StagePolicy("unknown", max_output_tokens=10), 10)
                        return "started"
                    except BudgetExceeded:
                        return "blocked"
                assert sorted(workers.map(call, range(2))) == ["blocked", "started"]

    with ThreadPoolExecutor(max_workers=1) as workers:
        first = workers.submit(first_request)
        started.wait(timeout=5)
        with Session(engine) as db, pytest.raises(BudgetExceeded):
            with request_budget_scope(db, "owner", "review"):
                pytest.fail("A second request bypassed the durable reservation")
        started.wait(timeout=5)
        first.result(timeout=5)
    with Session(engine) as db:
        assert usage_status(db, "owner")["daily"]["calls"] == 1
    engine.dispose()


def test_crashed_reservation_is_durable_and_other_user_does_not_share_limit(tmp_path):
    from career.usage_limits import _reserve

    engine = ledger(tmp_path)
    with Session(engine) as db:
        configure_usage(db, "owner", {"daily_calls": 1, "monthly_calls": 1})
        db.commit()
        _reserve(db, "owner", "provider_check")  # No settlement, as after a crash.
    engine.dispose()
    engine = ledger(tmp_path)
    with Session(engine) as db:
        state = usage_status(db, "owner")["monthly"]
        assert state["calls"] == 1 and state["reserved_calls"] == 1
        assert state["estimated_cost_usd"] is None
        db.rollback()
        with pytest.raises(BudgetExceeded):
            with request_budget_scope(db, "owner", "provider_check"):
                pass
        with request_budget_scope(db, "different-user", "provider_check"):
            pass
    engine.dispose()


def test_zero_ai_limit_preserves_manual_work_with_provider_connected(tmp_path, monkeypatch):
    from career.activity import run_operation
    from career.workflow import Workflow

    engine = ledger(tmp_path)
    monkeypatch.setattr("career.activity.provider_available", lambda: True)
    with Session(engine, expire_on_commit=False) as db:
        ws = Workflow(db, "owner").create("synthetic", "role", "jd")
        configure_usage(db, "owner", {"daily_calls": 0})
        db.commit()
        assert run_operation(db, "owner", ws.id, "generate", lambda: {"manual": True}, uses_ai=False) == {"manual": True}
        db.commit()
        assert usage_status(db, "owner")["daily"]["calls"] == 0
    engine.dispose()


def test_manual_junk_cannot_bypass_ai_limit_in_unsupported_action(client, monkeypatch):
    from career.api import app, database

    monkeypatch.setattr("career.activity.provider_available", lambda: True)
    client.headers["Authorization"] = "Bearer alice-key"
    workspace = client.post("/api/applications", json={"company": "synthetic", "role": "role", "jd_raw": "jd"}).json()
    session_generator = app.dependency_overrides[database]()
    db = next(session_generator)
    configure_usage(db, "alice", {"daily_calls": 0})
    db.commit()
    session_generator.close()
    base = "/api/applications/" + workspace["id"] + "/actions/"
    for action, body in [("revise", {"manual": {"junk": True}}), ("generate", {"manual": {}})]:
        result = client.post(base + action, json=body)
        assert result.status_code == 503
        assert "일·월 AI 사용 한도" in result.json()["detail"]
    manual = client.post(base + "analyze", json={"manual": {"actual_outputs": ["report"], "base_profession": "researcher"}})
    assert manual.status_code == 200


def test_standalone_scope_fails_fast_when_business_connection_is_already_held(tmp_path):
    engine = ledger(tmp_path)
    with Session(engine) as db:
        db.add(Record(user_id="owner", kind="pending", data={}))
        db.flush()
        with pytest.raises(ValueError, match="저장 작업"):
            with request_budget_scope(db, "owner", "provider_check"):
                pytest.fail("A quota connection was checked out behind the business connection")
    engine.dispose()


def test_standalone_reservation_latency_uses_the_original_request_deadline(tmp_path, monkeypatch):
    import career.request_budget as budget
    import career.usage_limits as limits

    clock = [100.0]
    monkeypatch.setattr(budget, "monotonic", lambda: clock[0])
    original = limits._reserve
    calls = []

    def delayed_reserve(*args):
        calls.append(True)
        envelope = original(*args)
        clock[0] = 175.0
        return envelope

    monkeypatch.setattr(limits, "_reserve", delayed_reserve)
    engine = ledger(tmp_path)
    with Session(engine) as db:
        with request_budget_scope(db, "owner", "provider_check"):
            assert budget.bounded_policy(StagePolicy("model", timeout_seconds=300)).timeout_seconds == 25
        assert len(calls) == 1
        clock[0] = 300.0
        with budget.deadline_scope(1):
            clock[0] = 302.0
            with pytest.raises(BudgetExceeded) as failure:
                with request_budget_scope(db, "owner", "provider_check"):
                    pytest.fail("An expired parent deadline restarted its budget")
            assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"
        assert len(calls) == 1
        assert budget.request_deadline.get() is None
    engine.dispose()


def test_reservation_that_exceeds_deadline_returns_unstarted_capacity(tmp_path, monkeypatch):
    import career.request_budget as budget
    import career.usage_limits as limits

    clock = [100.0]
    monkeypatch.setattr(budget, "monotonic", lambda: clock[0])
    original = limits._reserve

    def overrun(*args):
        envelope = original(*args)
        clock[0] = 201.0
        return envelope

    monkeypatch.setattr(limits, "_reserve", overrun)
    engine = ledger(tmp_path)
    with Session(engine) as db:
        with pytest.raises(BudgetExceeded):
            with request_budget_scope(db, "owner", "provider_check"):
                pytest.fail("AI must not start after an overlong reservation")
        assert usage_status(db, "owner")["daily"]["calls"] == 0
        assert usage_status(db, "owner")["daily"]["reserved_calls"] == 0
        assert limits.usage_envelope.get() is None
        assert budget.request_deadline.get() is None
    engine.dispose()


def test_real_adapter_parallel_review_has_no_worker_db_and_rollbacks_keep_usage(tmp_path, monkeypatch):
    import httpx2 as httpx
    from career.activity import run_operation
    from career.models import Artifact, PromptRun
    from career.parallel_qa import run
    from career.providers import ProviderUnavailable
    from career.request_budget import request_deadline
    from career.usage_limits import usage_envelope
    from career.workflow import Workflow
    from sqlalchemy import select
    from test_compatible_providers import Output, client, result

    monkeypatch.setenv("CAREER_LLM_PROVIDER", "huggingface")
    monkeypatch.setenv("HF_TOKEN", "hf_synthetic_not_real")
    monkeypatch.setenv("HF_FREE_ONLY_CONFIRMED", "1")
    envelopes, deadlines = [], []

    def handle(request):
        envelopes.append(id(usage_envelope.get()))
        deadlines.append(request_deadline.get())
        stage = json.loads(request.content)["response_format"]["json_schema"]["name"]
        return httpx.Response(200, json=result({"message": stage}))

    engine = ledger(tmp_path)
    instance = client(handle)
    with Session(engine, expire_on_commit=False) as db:
        service = Workflow(db, "owner", instance)
        ws = service.create("synthetic", "engineer", "report")
        db.commit()

        def operation():
            instance.structured("conversation_router", {}, Output)
            db.add(Artifact(user_id="owner", workspace_id=ws.id, kind="Draft", data={"text": "temporary"}))
            db.flush()
            run(service, [("fact_reviewer", {}, Output), ("recruiter", {}, Output)])
            raise ProviderUnavailable("Synthetic review is incomplete")

        with pytest.raises(ProviderUnavailable):
            run_operation(db, "owner", ws.id, "conversation", operation)
        assert list(db.scalars(select(Artifact))) == []
        assert len(list(db.scalars(select(PromptRun)))) == 3
        status = usage_status(db, "owner")["daily"]
        assert status["calls"] == 3 and status["tokens"] == 90
        assert status["reserved_calls"] == 0
        assert len(set(envelopes)) == 1 and len(set(deadlines)) == 1
        assert deadlines[0] is not None
    instance.client.close()
    engine.dispose()


def test_cost_limit_blocks_unknown_price_before_call_and_returns_unused_capacity(tmp_path, monkeypatch):
    engine = ledger(tmp_path)
    with Session(engine) as db:
        configure_usage(db, "owner", {"daily_cost_usd": 0.01})
        db.commit()
        with request_budget_scope(db, "owner", "provider_check") as quota:
            with pytest.raises(BudgetExceeded) as failure:
                quota.draw(StagePolicy("unknown", max_output_tokens=100), 100)
            assert failure.value.code == "COST_BUDGET_UNVERIFIABLE"
        assert usage_status(db, "owner")["daily"]["calls"] == 0
        db.commit()
        monkeypatch.setenv("CAREER_LLM_PRICING_JSON", json.dumps({"known": {
            "input_usd_per_million": 2, "cached_input_usd_per_million": 0.5,
            "cache_write_usd_per_million": 2, "output_usd_per_million": 8}}))
        with request_budget_scope(db, "owner", "provider_check") as quota:
            ticket = quota.draw(StagePolicy("known", max_output_tokens=100), 100)
            quota.settle_call(ticket, "known", {"input_tokens": 50, "output_tokens": 20, "input_tokens_details": {}})
        state = usage_status(db, "owner")["daily"]
        assert state["calls"] == 1 and state["tokens"] == 70
        assert 0.00026 <= state["estimated_cost_usd"] <= 0.000261
    engine.dispose()


@pytest.mark.parametrize("known_search_price", [True, False])
def test_web_search_calls_and_missing_tool_price_reach_the_durable_ledger(tmp_path, monkeypatch, known_search_price):
    from types import SimpleNamespace

    from career.providers import OpenAIWebResearchProvider
    from test_runtime_trace import research_result, sdk_provider, usage

    rates: dict[str, float] = {"input_usd_per_million": 2, "cached_input_usd_per_million": 1,
                              "cache_write_usd_per_million": 2, "output_usd_per_million": 4}
    if known_search_price:
        rates["web_search_usd_per_call"] = 0.01
    monkeypatch.setenv("CAREER_LLM_PRICING_JSON", json.dumps({"fixture-openai": rates}))
    provider = sdk_provider(
        parsed=lambda **_kw: SimpleNamespace(output_parsed=research_result(), usage=usage()),
        created=lambda **_kw: SimpleNamespace(output_text="synthetic research", usage=usage(),
                                             output=[SimpleNamespace(type="web_search_call") for _ in range(2)]),
    )
    engine = ledger(tmp_path)
    with Session(engine) as db:
        with request_budget_scope(db, "owner", "research"):
            assert OpenAIWebResearchProvider(provider).research("synthetic", "role", "jd").sources == []
        state = usage_status(db, "owner")["daily"]
        assert state["calls"] == 2 and state["tokens"] == 36
        assert state["reserved_calls"] == 0
        if known_search_price:
            # Both responses cost 48 microdollars in tokens, plus two searches.
            assert state["estimated_cost_usd"] == pytest.approx(0.020096, abs=0.000002)
            assert state["unknown_cost_calls"] == 0
        else:
            assert state["estimated_cost_usd"] is None
            assert state["unknown_cost_calls"] == 1
            assert state["known_estimated_cost_usd"] == pytest.approx(0.000048, abs=0.000001)
    engine.dispose()


def test_unobserved_tool_count_remains_unknown_in_the_ledger(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from test_runtime_trace import sdk_provider, usage

    monkeypatch.setenv("CAREER_LLM_PRICING_JSON", json.dumps({"fixture-openai": {
        "input_usd_per_million": 2, "cached_input_usd_per_million": 1,
        "cache_write_usd_per_million": 2, "output_usd_per_million": 4,
        "web_search_usd_per_call": 0.01}}))
    provider = sdk_provider()
    engine = ledger(tmp_path)
    with Session(engine) as db:
        with request_budget_scope(db, "owner", "provider_check"):
            assert provider._observe(
                "web_search", "web_search", "fixture-openai", {},
                lambda: SimpleNamespace(usage=usage()), lambda _response: "result",
                count_tools=lambda _response: None,
            ) == "result"
        state = usage_status(db, "owner")["daily"]
        assert state["calls"] == 1 and state["tokens"] == 18
        assert state["unknown_cost_calls"] == 1
        assert state["estimated_cost_usd"] is None
        assert state["known_estimated_cost_usd"] == 0
    engine.dispose()


def test_settlement_failure_keeps_reservation_without_masking_a_successful_scope(tmp_path, monkeypatch):
    import career.usage_limits as limits
    from career.models import AIUsageReservation
    from career.request_budget import request_deadline
    from sqlalchemy import select

    def unavailable(_envelope):
        raise RuntimeError("synthetic ledger outage")

    monkeypatch.setattr(limits, "_settle", unavailable)
    engine = ledger(tmp_path)
    with Session(engine) as db:
        with request_budget_scope(db, "owner", "provider_check") as quota:
            ticket = quota.draw(StagePolicy("no-rate", max_output_tokens=100), 300)
            quota.settle_call(ticket, "no-rate", {"input_tokens": 50, "output_tokens": 20})
        assert limits.usage_envelope.get() is None
        assert request_deadline.get() is None
        state = usage_status(db, "owner")["daily"]
        assert state["calls"] == state["reserved_calls"] == 1
        assert state["tokens"] == state["reserved_tokens"] == limits.CAPACITY_TOKENS_PER_CALL
        assert state["estimated_cost_usd"] is None
        assert db.scalar(select(AIUsageReservation.status)) == "RESERVED"
    engine.dispose()


def test_settlement_failure_preserves_operation_error_and_releases_every_context(tmp_path, monkeypatch):
    import career.usage_limits as limits
    from career.activity import execution_id, run_operation
    from career.models import AIUsageReservation, ExecutionRun
    from career.providers import ProviderUnavailable
    from career.request_budget import request_deadline
    from career.runtime_trace import trace_context, trace_sink
    from career.workflow import Workflow
    from sqlalchemy import select

    def unavailable(_envelope):
        raise RuntimeError("synthetic ledger outage")

    monkeypatch.setattr(limits, "_settle", unavailable)
    monkeypatch.setattr("career.activity.provider_available", lambda: True)
    engine = ledger(tmp_path)
    with Session(engine, expire_on_commit=False) as db:
        workspace = Workflow(db, "owner").create("synthetic", "role", "jd")
        db.commit()
        original = ProviderUnavailable("synthetic original provider failure")

        def operation():
            quota = limits.usage_envelope.get()
            assert quota is not None
            quota.draw(StagePolicy("no-rate", max_output_tokens=100), 300)
            db.add(Record(user_id="owner", kind="temporary", data={}))
            db.flush()
            raise original

        with pytest.raises(ProviderUnavailable) as failure:
            run_operation(db, "owner", workspace.id, "generate", operation)
        assert failure.value is original
        assert execution_id.get() is None and limits.usage_envelope.get() is None
        assert request_deadline.get() is None and trace_sink.get() is None
        assert trace_context.get() == {}
        assert db.scalar(select(Record).where(Record.kind == "temporary")) is None
        assert db.scalar(select(ExecutionRun.status)) == "FAILED"
        assert db.scalar(select(AIUsageReservation.status)) == "RESERVED"
        state = usage_status(db, "owner")["daily"]
        assert state["calls"] == state["reserved_calls"] == 2
        assert state["tokens"] == state["reserved_tokens"] == 2 * limits.CAPACITY_TOKENS_PER_CALL
    engine.dispose()


@pytest.mark.parametrize("value", [{"unknown": 1}, {"daily_calls": True}, {"monthly_tokens": -1},
                                    {"daily_cost_usd": float("nan")}, {"monthly_cost_usd": "0.1"}])
def test_limit_configuration_rejects_unknown_fields_or_invalid_numbers(value):
    with pytest.raises(ValueError):
        validate_limits(value)
