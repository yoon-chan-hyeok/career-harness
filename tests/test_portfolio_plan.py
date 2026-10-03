# ruff: noqa: F811 -- reusable workflow fixture
import pytest
from career.portfolio import approve, plan
from career.providers import FakeLLMProvider
from career.schemas import EvidenceItem
from test_workflow import flow  # noqa: F401


def test_portfolio_has_distinct_roles_and_message_candidates_then_requires_approval(flow):
    service, ws, evidence = flow
    service.approve_strategy(ws.id)
    questions = [service.add_question(ws.id, text, 1000) for text in ("지원동기", "직무역량")]
    manual = {
        "items": [
            {
                "question_id": q["id"],
                "evaluation_intent": q["text"],
                "identity_role": f"역할 {index}",
                "primary_message_candidates": [f"판단 {index}"],
                "evidence_candidate_ids": [evidence.id],
                "avoided_repetition": ["같은 수치 반복"],
            }
            for index, q in enumerate(questions)
        ]
    }
    portfolio = plan(service, ws.id, manual)
    brief = {
        "question_id": questions[0]["id"],
        "question_type": "MOTIVATION",
        "evaluation_intent": "선택 이유",
        "primary_message": "판단 0",
        "evidence_ids": [evidence.id],
    }
    with pytest.raises(ValueError, match="승인"):
        service.question_brief(ws.id, questions[0]["id"], brief)
    approve(service, ws.id)
    result = service.question_brief(ws.id, questions[0]["id"], brief)
    assert portfolio.id in result.depends_on
    service.add_question(ws.id, "협업", 1000)
    assert portfolio.status == "STALE" and result.status == "STALE"


def test_next_step_allocates_multiple_questions_before_single_question(flow):
    service, ws, evidence = flow
    service.approve_strategy(ws.id)
    questions = [service.add_question(ws.id, text, 1000) for text in ("지원동기", "직무역량")]
    service.provider = FakeLLMProvider({"question_portfolio": {"items": [
        {"question_id": q["id"], "evaluation_intent": q["text"], "identity_role": str(index),
         "primary_message_candidates": [f"메시지 {index}"], "evidence_candidate_ids": [evidence.id],
         "avoided_repetition": []} for index, q in enumerate(questions)
    ]}})
    result = service.command(ws.id, "ㄱㄱ", questions[0]["id"])
    assert result["patched_artifacts"] == [service.artifact(ws.id, "QuestionPortfolio").id]
    with pytest.raises(ValueError, match="역할과 메시지"):
        service.command(ws.id, "ㄱㄱ", questions[0]["id"])


def test_mapping_rejects_invented_hook_before_question_writer_can_see_it(flow):
    service, ws, evidence = flow
    pack = service.artifact(ws.id, "EvidencePack")
    item = {k: v for k, v in pack.data["items"][0].items() if k in EvidenceItem.model_fields}
    item["understandable_hook"] = "Invented result"
    with pytest.raises(ValueError, match="원문"):
        service.map_evidence(ws.id, {"items": [item], "uncovered_outputs": []})
