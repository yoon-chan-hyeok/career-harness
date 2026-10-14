# ruff: noqa: F811 -- reusable workflow fixture
import pytest
from career.conversation import ChatRequest, converse
from career.providers import FakeLLMProvider
from career.resume import legacy_sections
from test_workflow import doc, finish, flow, verify_claim  # noqa: F401


@pytest.mark.parametrize("pages", [2, "MASTER"])
def test_resume_regeneration_retains_budget_until_user_explicitly_changes_it(flow, pages):
    service, workspace, evidence = flow
    service.approve_strategy(workspace.id)
    service.provider = FakeLLMProvider({"resume_writer": legacy_sections(doc(evidence))})
    original = service.resume(workspace.id, doc(evidence), page_budget=pages)
    service.command(workspace.id, "다시", resume=True)
    repeated = service.artifact(workspace.id, "ResumeContent")
    assert repeated.data["page_budget"] == pages
    assert repeated.data["character_budget"] == original.data["character_budget"]
    changed = service.resume(workspace.id, doc(evidence), page_budget=1)
    assert changed.data["page_budget"] == 1 and changed.data["character_budget"] == 3500
    with pytest.raises(ValueError, match="분량"):
        service.resume(workspace.id, doc(evidence), page_budget="UNSUPPORTED")


def test_selected_latest_stale_document_cannot_bypass_claim_approval(flow):
    service, workspace, evidence = flow
    question = finish(service, workspace, evidence)
    qid = question["id"]
    draft = service.artifact(workspace.id, "Draft", qid)
    old_brief = service.artifact(workspace.id, "QuestionBrief", qid)
    from career.schemas import QuestionBrief

    brief = {key: value for key, value in old_brief.data.items() if key in QuestionBrief.model_fields}
    service.question_brief(workspace.id, qid, brief)
    assert draft.status == "STALE"
    # Even selecting the latest old document and explicitly asking to lock it
    # cannot approve a new message without its current Evidence Test.
    blocked = converse(service, workspace.id, ChatRequest(text="잠가", client_id="recovery-lock-001",
                        question_id=qid, artifact_id=draft.id))
    assert blocked["data"]["response"]["status"] == "NEEDS_INPUT"
    assert service.artifact(workspace.id, "QuestionBrief", qid).status == "ACTIVE"
    assert draft.status == "STALE"
    verify_claim(service, workspace, qid)
    blocked = converse(service, workspace.id, ChatRequest(text="ㄱㄱ", client_id="recovery-next-002",
                        question_id=qid, artifact_id=draft.id))
    assert blocked["data"]["response"]["status"] == "NEEDS_INPUT"
    assert "승인" in blocked["data"]["response"]["text"]
    service.approve_question(workspace.id, qid)
    service.provider = FakeLLMProvider({"writer": doc(evidence)})
    result = converse(service, workspace.id, ChatRequest(text="ㄱㄱ", client_id="recovery-next-003",
                       question_id=qid, artifact_id=draft.id))
    assert result["data"]["response"]["status"] == "OK"
    current = service.artifact(workspace.id, "Draft", qid)
    assert current.version == draft.version + 1 and current.status == "ACTIVE"
    assert draft.status == "SUPERSEDED"


def test_latest_stale_resume_still_requires_current_strategy_approval(flow):
    service, workspace, evidence = flow
    service.approve_strategy(workspace.id)
    resume = service.resume(workspace.id, doc(evidence), page_budget=2)
    current_strategy = service.artifact(workspace.id, "ApplicationBrief")
    service.strategy(workspace.id, current_strategy.data)
    assert resume.status == "STALE"
    blocked = converse(service, workspace.id, ChatRequest(text="ㄱㄱ", client_id="recovery-resume-001",
                        artifact_id=resume.id))
    assert blocked["data"]["response"]["status"] == "NEEDS_INPUT"
    assert "전략 승인" in blocked["data"]["response"]["text"]
    assert resume.status == "STALE"
