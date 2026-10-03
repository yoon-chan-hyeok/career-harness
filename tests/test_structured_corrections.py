# ruff: noqa: F811 -- reuse real workflow fixture
import pytest
from career.artifacts import latest
from career.conversation import ChatRequest, converse
from career.structured_corrections import apply, pending, propose
from career.workflow import Workflow
from test_workflow import flow, question  # noqa: F401


def test_role_patch_requires_approval_preserves_other_fields_and_stales_dependencies(flow):
    service, ws, evidence = flow
    service.approve_strategy(ws.id)
    q = question(service, ws, evidence)
    role = service.artifact(ws.id, "OpportunityBrief")
    strategy = service.artifact(ws.id, "ApplicationBrief")
    proposal = propose(
        service,
        ws.id,
        role.id,
        {"base_profession": role.data["base_profession"]},
        {"base_profession": "실험 설계 연구원"},
        "본업 해석을 바꿔 주세요",
    )
    assert service.artifact(ws.id, "OpportunityBrief").id == role.id
    with pytest.raises(ValueError, match="승인"):
        apply(service, ws.id, proposal["id"])
    result = apply(service, ws.id, proposal["id"], confirmed=True)
    assert result["data"]["status"] == "ACCEPTED"
    corrected = service.artifact(ws.id, "OpportunityBrief")
    assert corrected.data["base_profession"] == "실험 설계 연구원"
    assert corrected.data["actual_outputs"] == role.data["actual_outputs"]
    assert corrected.version == role.version + 1
    assert strategy.status == "STALE"
    dependent = latest(service.db, service.user, ws.id, "QuestionBrief", q["id"])
    assert dependent is not None and dependent.status == "STALE"
    assert pending(service, ws.id) == []


def test_patch_checks_current_version_source_boundary_and_owner(flow):
    service, ws, _ = flow
    role = service.artifact(ws.id, "OpportunityBrief")
    with pytest.raises(ValueError, match="항목"):
        propose(service, ws.id, role.id, {"company_facts": []}, {"company_facts": []}, "fabricate")
    with pytest.raises(ValueError, match="다릅니다"):
        propose(
            service, ws.id, role.id, {"base_profession": "wrong"}, {"base_profession": "other"}, "fixture"
        )
    proposal = propose(
        service,
        ws.id,
        role.id,
        {"base_profession": role.data["base_profession"]},
        {"base_profession": "검증 연구원"},
        "fixture",
    )
    with pytest.raises(LookupError):
        apply(Workflow(service.db, "other"), ws.id, proposal["id"], confirmed=True)
    service.analyze(ws.id, role.data)
    with pytest.raises(ValueError, match="버전"):
        apply(service, ws.id, proposal["id"], confirmed=True)


def test_free_conversation_proposes_positioning_without_silent_approval(flow):
    service, ws, _ = flow
    current = service.artifact(ws.id, "ApplicationBrief")

    class Router:
        def structured(self, stage, context, schema):
            assert stage == "conversation_router"
            return schema.model_validate(
                {
                    "reply": "교정 제안",
                    "action": "correct-analysis",
                    "field_changes": [
                        {
                            "field": "positioning",
                            "old_value": current.data["positioning"],
                            "new_value": "평가 실험 담당 연구원",
                        }
                    ],
                }
            )

    service.provider = Router()
    response = converse(
        service,
        ws.id,
        ChatRequest(
            text="포지셔닝을 평가 실험 담당으로 고쳐줘",
            client_id="analysis-correction-01",
            artifact_id=current.id,
        ),
    )
    assert response["data"]["response"]["status"] == "WAITING_REVIEW"
    assert service.artifact(ws.id, "ApplicationBrief").id == current.id
    assert ws.state == "WAITING_STRATEGY_APPROVAL"
    apply(service, ws.id, response["data"]["response"]["proposal_id"], confirmed=True)
    assert service.artifact(ws.id, "ApplicationBrief").data["positioning"] == "평가 실험 담당 연구원"
    assert ws.state == "WAITING_STRATEGY_APPROVAL"


def test_default_next_runs_fit_assessment_before_strategy(flow):
    service, ws, _ = flow
    # Default routing is state-driven; direct manual API can still be used.
    ws.state = "EVIDENCE_READY"

    class Assessment:
        def structured(self, stage, context, schema):
            assert stage == "opportunity_assessment"
            return schema.model_validate(
                {
                    "eligibility": [],
                    **{
                        key: {"level": "UNKNOWN", "reason": "확인 필요"}
                        for key in ("fit", "career_value", "action_priority")
                    },
                    "selection_risks": [],
                    "preparation_cost": "UNKNOWN",
                    "recommendation": "LOW_PRIORITY",
                    "main_fix": "현재 채용 상태 확인",
                }
            )

    service.provider = Assessment()
    service.command(ws.id, "ㄱㄱ")
    assert service.artifact(ws.id, "OpportunityAssessment") is not None
