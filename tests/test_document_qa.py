from career.document_qa import portfolio_qa, skimmability_qa


def test_same_project_allowed_when_messages_differ():
    briefs = [
        {"primary_message": "실험 설계", "evidence_ids": ["same"]},
        {"primary_message": "팀 조율", "evidence_ids": ["same"]},
    ]
    assert not portfolio_qa(briefs, [])


def test_duplicate_message_rejected_and_metric_warned():
    issues = portfolio_qa([{"primary_message": "same"}] * 2, [{"text": "80%"}] * 2)
    assert {i["code"] for i in issues} == {"DUPLICATE_MESSAGE", "REPEATED_METRIC"}


def test_resume_skimming():
    assert any(i["code"] == "TOOL_FIRST" for i in skimmability_qa("- Python, SQL로 분석"))
    assert not skimmability_qa("- 오류를 분류하는 평가 보고서를 작성하고 원인을 검증했습니다.")
