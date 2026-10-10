# ruff: noqa: F811 -- reusable workflow fixture
import json

import httpx2 as httpx
import pytest
from career.compatible_providers import CompatibleProvider
from career.models import Artifact, PromptRun
from career.provider_config import ProviderSettings
from career.provider_policy import stage_policy
from career.providers import ProviderUnavailable, configured_provider
from career.resume import ResumeContent
from career.runtime_trace import trace_sink
from career.schemas import ApplicationBrief, Document, EvidencePack, OpportunityBrief, QuestionBrief, Review
from openai import DefaultHttpxClient, OpenAI
from pydantic import BaseModel
from sqlalchemy import select
from test_workflow import doc, flow, question  # noqa: F401

SECRET = "hf_fixture_private_token_not_real"


@pytest.mark.parametrize("stage,schema", [("opportunity", OpportunityBrief), ("evidence_mapper", EvidencePack),
    ("strategy", ApplicationBrief), ("question_brief", QuestionBrief), ("writer", Document),
    ("resume_writer", ResumeContent), ("fact_reviewer", Review), ("recruiter", Review)])
def test_groq_actual_contracts_and_korean_context_fit_without_network(stage, schema):
    from career.prompt_cache import prepare
    from career.prompts import instructions_for
    from career.provider_policy import BudgetExceeded

    instance = client(lambda _: pytest.fail("Preflight must be offline"), "groq")
    policy = instance._policy(stage)
    format = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema(), "strict": False}}
    prompt = prepare(stage, {"evidence": "분석 기준을 정하고 실험 결과를 검토했습니다. " * 10},
                     instructions_for(stage), policy.model, "groq", format)
    request = {"messages": [{"role": "system", "content": prompt.instructions}, {"role": "user", "content": prompt.content}],
               "response_format": format, "model": policy.model}
    assert instance._validate_input(policy, request) + policy.max_output_tokens + 256 <= 8000
    with pytest.raises(BudgetExceeded):
        instance._validate_input(policy, {**request, "extra_evidence": "서로 다른 수치와 정확한 근거 " * 15000})
    instance.client.close()


class Output(BaseModel):
    message: str


def client(handler, provider="huggingface"):
    model = "openai/gpt-oss-120b:fireworks-ai" if provider == "huggingface" else "openai/gpt-oss-120b"
    instance = CompatibleProvider(ProviderSettings(provider, model, SECRET, True, "local_private_file"))
    instance.client.close()
    instance.client = OpenAI(
        api_key=SECRET,
        base_url="https://router.huggingface.co/v1" if provider == "huggingface" else "https://api.groq.com/openai/v1",
        max_retries=0,
        http_client=DefaultHttpxClient(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    return instance


def result(data, finish="stop"):
    return {
        "id": "synthetic", "object": "chat.completion", "created": 1, "model": "upstream",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(data)}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30},
    }


@pytest.mark.parametrize("provider", ["huggingface", "groq"])
def test_official_chat_protocol_validates_schema_and_retains_private_operational_trace(provider):
    calls, traces = [], []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=result({"message": "연결 확인"}))

    instance = client(handle, provider)
    sink = trace_sink.set(lambda stage, name, data: traces.append((stage, name, data)))
    try:
        assert instance.structured("resume_writer", {"private": "private career source"}, Output).message == "연결 확인"
    finally:
        trace_sink.reset(sink)
        instance.client.close()
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    assert body["response_format"]["type"] == "json_schema"
    assert body["max_tokens"] <= 4096 and body["stream"] is False
    assert body["model"].startswith("openai/gpt-oss-120b")
    assert calls[0].url.path.endswith("/chat/completions")
    assert traces[0][2]["usage"]["input_tokens"] == 21
    assert traces[0][2]["usage"]["output_tokens"] == 9
    assert traces[0][2]["model"] == body["model"]
    assert traces[0][2]["prompt_template_version"]
    assert len(traces[0][2]["output_hash"]) == 64
    encoded = json.dumps(traces)
    assert SECRET not in encoded and "private career source" not in encoded and "연결 확인" not in encoded


@pytest.mark.parametrize("status", [401, 402, 429, 500, 302])
def test_upstream_failure_never_retries_redirects_or_switches_to_paid_provider(status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://unexpected.example/steal"}, json={"error": {"message": SECRET}})

    instance = client(handle)
    with pytest.raises(ProviderUnavailable) as failure:
        instance.structured("writer", {}, Output)
    assert SECRET not in str(failure.value)
    assert len(calls) == 1 and calls[0].url.host == "router.huggingface.co"
    assert instance.last_trace["status"] == "FAILED"
    instance.client.close()


@pytest.mark.parametrize("payload,finish", [({"invalid": True}, "stop"), ({"message": "partial"}, "length")])
def test_schema_invalid_and_incomplete_results_are_rejected(payload, finish):
    instance = client(lambda _: httpx.Response(200, json=result(payload, finish)))
    with pytest.raises(ProviderUnavailable):
        instance.structured("writer", {}, Output)
    instance.client.close()


def test_free_acknowledgement_is_required_without_implicit_openai_fallback(monkeypatch):
    monkeypatch.setenv("CAREER_LLM_PROVIDER", "huggingface")
    monkeypatch.setenv("HF_TOKEN", SECRET)
    monkeypatch.setenv("OPENAI_API_KEY", "another_private_key")
    monkeypatch.setenv("OPENAI_MODEL", "commercial-model")
    with pytest.raises(ProviderUnavailable):
        configured_provider()
    monkeypatch.setenv("HF_FREE_ONLY_CONFIRMED", "1")
    instance = configured_provider()
    assert isinstance(instance, CompatibleProvider)
    with pytest.raises(ProviderUnavailable):
        instance.embed(["source"])
    instance.client.close()


def test_generic_stage_policy_accepts_hf_identifiers_without_changing_legacy_defaults(monkeypatch):
    monkeypatch.setenv("CAREER_LLM_MAX_OUTPUT_TOKENS", "1024")
    monkeypatch.setenv("CAREER_LLM_STAGE_POLICIES", json.dumps({"writer": {"timeout_seconds": 40}}))
    policy = stage_policy("writer", "openai/gpt-oss-120b:fireworks-ai")
    assert policy.max_output_tokens == 1024 and policy.timeout_seconds == 40


@pytest.mark.parametrize("provider", ["huggingface", "groq"])
def test_chat_adapter_creates_both_cover_letter_and_structured_resume_in_product_workflow(flow, provider):
    service, workspace, evidence = flow
    service.approve_strategy(workspace.id)
    q = question(service, workspace, evidence)
    service.approve_question(workspace.id, q["id"])
    cover_letter = doc(evidence)
    resume = {"sections": [{"title": "프로젝트", "kind": "PROJECT", "bullets": [{
        "text": evidence.body, "evidence_ids": [evidence.id], "claims": cover_letter["claims"],
    }]}]}
    calls = []

    def handle(request):
        payload = json.loads(request.content)
        calls.append(payload)
        data = resume if payload["response_format"]["json_schema"]["name"] == "ResumeContent" else cover_letter
        return httpx.Response(200, json=result(data))

    instance = client(handle, provider)
    service.provider = instance
    draft = service.draft(workspace.id, q["id"])
    written_resume = service.resume(workspace.id)
    assert ResumeContent.model_validate({"sections": written_resume.data["sections"]})
    service.db.commit()
    service.db.expire_all()
    assert service.db.get(Artifact, draft.id).data["text"] == evidence.body
    assert evidence.body in service.db.get(Artifact, written_resume.id).data["text"]
    traces = list(service.db.scalars(select(PromptRun).where(PromptRun.user_id == service.user)))
    assert [row.stage for row in traces] == ["writer", "resume_writer"]
    assert all(row.provider == ("HuggingFace" if provider == "huggingface" else "Groq") for row in traces)
    assert [call["response_format"]["json_schema"]["name"] for call in calls] == ["Document", "ResumeContent"]
    instance.client.close()
