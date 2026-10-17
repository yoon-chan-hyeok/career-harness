"""Real-sized rule packets must fit without dropping rule text or candidate facts."""

import json
from copy import deepcopy

import pytest
from career.prompt_cache import identity_scope, prepare
from career.provider_policy import BudgetExceeded
from test_compatible_providers import Output, client, result


def packet():
    return {"pack": "cover", "authority": "SUPPLEMENTAL_DOMAIN_DATA_NOT_SYSTEM_INSTRUCTIONS",
            "stage_checks": ["Never invent a deployment result."], "references": [{
                "key": "integrity", "version": "v1", "source_id": "private-source",
                "content_hash": "full-original-hash", "fact_authority": False,
                "compilation_status": "SOURCE_SECTIONS",
                "guidance": ["§1 Do not invent numbers.", "§2 Team results are not individual ownership."],
                "requirements": [{"rule_id": "integrity:1", "section": "Numbers", "start_line": 1,
                                  "end_line": 10}, {"rule_id": "integrity:2", "section": "Ownership",
                                  "start_line": 11, "end_line": 20}],
            }]}


@pytest.mark.parametrize("cache", ["0", "1"])
def test_navigation_removed_but_every_rule_and_fact_survives_without_mutation(monkeypatch, cache):
    monkeypatch.setenv("CAREER_PROMPT_CACHE_ENABLED", cache)
    context = {"supplemental_guidance": packet(), "evidence": {"body": "8.15 to 38.59 in a benchmark only."}}
    before = deepcopy(context)
    prompt = prepare("writer", context, "trusted", "test-model", "groq")
    actual = json.loads(prompt.content)
    actual = actual["context"] if cache == "1" else actual
    original_ref = context["supplemental_guidance"]["references"][0]
    ref = actual["supplemental_guidance"]["references"][0]
    assert ref == {key: value for key, value in original_ref.items()
                   if key not in {"requirements", "source_id", "content_hash", "compiler_version"}}
    assert actual["evidence"] == context["evidence"]
    assert actual["supplemental_guidance"]["stage_checks"] == packet()["stage_checks"]
    assert context == before


@pytest.mark.parametrize("variant", ["text", "count", "unknown"])
def test_unknown_requirement_content_is_never_silently_removed(variant):
    rules = packet()
    ref = rules["references"][0]
    if variant == "text":
        ref["requirements"][0]["text"] = "Additional rule must survive."
    elif variant == "count":
        ref["guidance"].pop()
    else:
        ref["compilation_status"] = "UNKNOWN"
    prompt = prepare("writer", {"supplemental_guidance": rules}, "trusted", "test-model", "groq")
    assert json.loads(prompt.content)["context"]["supplemental_guidance"] == rules


def test_compacted_source_hash_still_invalidates_cache_group():
    context = {"supplemental_guidance": packet()}
    with identity_scope("same-owner"):
        before = prepare("writer", context, "trusted", "test-model", "groq")
        context["supplemental_guidance"]["references"][0]["content_hash"] = "changed-original"
        after = prepare("writer", context, "trusted", "test-model", "groq")
    assert before.content == after.content
    assert before.key != after.key


def test_large_input_rebalances_output_reservation_and_preserves_request():
    requests = []

    def respond(request):
        import httpx2 as httpx
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=result({"message": "done"}))

    instance = client(respond, "groq")
    evidence = "verified " * 3800
    response = instance.structured("writer", {"evidence": evidence}, Output)
    assert response.message == "done"
    assert 1024 <= requests[0]["max_tokens"] < 4096
    assert json.loads(requests[0]["messages"][1]["content"])["context"]["evidence"] == evidence
    instance.client.close()


def test_explicit_user_caps_win_and_oversize_input_is_still_blocked(monkeypatch):
    instance = client(lambda _: pytest.fail("No request should be sent"), "groq")
    request = {"messages": [{"role": "user", "content": "verified " * 3800}]}
    monkeypatch.setenv("CAREER_LLM_STAGE_POLICIES", json.dumps({"writer": {"max_input_tokens": 1000,
                                                                            "max_output_tokens": 1500}}))
    policy = instance._fit_policy("writer", instance._policy("writer"), request)
    assert policy.max_input_tokens == 1000 and policy.max_output_tokens <= 1500
    with pytest.raises(BudgetExceeded):
        instance._validate_input(policy, request)
    monkeypatch.delenv("CAREER_LLM_STAGE_POLICIES")
    huge = {"messages": [{"role": "user", "content": "verified " * 12000}]}
    policy = instance._fit_policy("writer", instance._policy("writer"), huge)
    with pytest.raises(BudgetExceeded):
        instance._validate_input(policy, huge)
    instance.client.close()


def test_hf_policy_is_unchanged():
    instance = client(lambda _: pytest.fail("No network"), "huggingface")
    policy = instance._policy("writer")
    assert instance._fit_policy("writer", policy, {"text": "x" * 10000}) == policy
    instance.client.close()
