# ruff: noqa: F811 -- shared workflow fixture
from copy import deepcopy

from career.domain import save_entity
from career.preparation import preparation_context
from career.promotion import direct_preference
from career.truth import add_fact, register_source
from career.workflow import Workflow
from test_workflow import flow, question  # noqa: F401


class Capture:
    last_trace = {"model": "preparation-fixture"}

    def __init__(self, payload):
        self.payload, self.calls = payload, {}

    def structured(self, stage, context, schema):
        self.calls[stage] = deepcopy(context)
        return schema.model_validate(self.payload)


def test_mapping_reads_current_corrections_and_scoped_rules_before_ai(flow):
    service, workspace, evidence = flow
    source, _ = register_source(service.db, "a", "corrections/profile", "Current degree", "USER_CORRECTION")
    fact = add_fact(service.db, "a", source.id, "profile", "degree", {"text": "학사"})
    rule = direct_preference(service.db, "a", "산출물을 먼저 설명합니다.",
                             "ROLE_TYPE", workspace.role, confirmed=True)
    current = service.artifact(workspace.id, "EvidencePack")
    payload = {"items": [{k: v for k, v in current.data["items"][0].items() if k in {
        "evidence_id", "job_output_id", "classification", "evidence_strength", "ownership_strength", "rationale"
    }}], "uncovered_outputs": []}
    capture = Capture(payload)
    service.provider = capture
    result = service.map_evidence(workspace.id)
    prep = capture.calls["evidence_mapper"]["preparation"]
    assert prep["current_corrections"][0]["fact_id"] == fact.id
    assert prep["verified_writing_guidance"][0]["rule"] == rule["data"]["rule"]
    assert source.id in result.source_ids


def test_question_designer_receives_original_and_confirmed_decision_scope(flow):
    service, workspace, evidence = flow
    episode = save_entity(service.db, "a", "DecisionEpisode", {
        "source_id": evidence.source_id, "evidence_id": evidence.id, "situation": "평가",
        "constraint": "작은 표본", "observation": "표본별 편차", "options": ["전체 비교", "표본 분리"],
        "decision": "표본을 분리", "action": "재평가", "outcome": "차이 관찰", "lesson": "범위 명시",
    }, explicit_confirmation=True)
    # New truth intentionally invalidates dependent stages; rebuild them.
    service.analyze(workspace.id, {"actual_outputs": ["평가 보고서"], "base_profession": "평가 연구원"})
    service.map_evidence(workspace.id, {"items": [{
        "evidence_id": evidence.id, "job_output_id": "평가 보고서", "classification": "DIRECT",
        "evidence_strength": "STRONG", "ownership_strength": "STRONG", "rationale": "실험",
    }], "uncovered_outputs": []})
    service.strategy(workspace.id, {"positioning": "연구원", "base_profession_identity": "연구원",
        "main_skill_message": "평가", "assignment_statement": "평가 보고서를 작성"})
    service.approve_strategy(workspace.id)
    q = service.add_question(workspace.id, "판단을 바꾼 경험", 1000)
    capture = Capture({"question_id": q["id"], "question_type": "CHALLENGE", "evaluation_intent": "판단",
                       "primary_message": "표본을 나누어 평가", "evidence_ids": [evidence.id]})
    service.provider = capture
    result = service.question_brief(workspace.id, q["id"])
    selected = capture.calls["question_brief"]["evidence"][0]
    assert selected["body"] == evidence.body
    assert selected["data"]["confirmed_decision_episodes"][0]["id"] == episode.id
    assert selected["data"]["ownership"]["implementation"] == "USER"
    assert evidence.source_id in result.source_ids
    assert "style_projections" in capture.calls["question_brief"]


def test_postmortem_is_scoped_historical_signal_not_a_promoted_rule(flow):
    service, old, evidence = flow
    service.outcome(old.id, "ASSESSMENT_FAIL", "코딩 테스트 시간 부족")
    postmortem = service.postmortem(old.id)
    current = service.create("다른 회사", old.role, "평가 보고서 작성")
    prep = preparation_context(service, current, service.selected([evidence.id]))
    historical = prep["context"]["previous_postmortems"]
    assert len(historical) == 1
    assert historical[0]["attribution_scope"] == "ASSESSMENT"
    assert "NOT_CAUSE_OR_WRITING_RULE" in historical[0]["authority"]
    assert not prep["context"]["verified_writing_guidance"]
    assert prep["depends_on"] == [postmortem.id]
    assert not preparation_context(service, old, [])["depends_on"]
    unrelated = service.create("타사", "회계", "결산")
    assert not preparation_context(service, unrelated, [])["context"]["previous_postmortems"]
    other = Workflow(service.db, "other")
    other_ws = other.create(old.company, old.role, "평가")
    assert not preparation_context(other, other_ws, [])["context"]["previous_postmortems"]


def test_superseded_correction_never_overrides_current_truth(flow):
    service, workspace, _ = flow
    old, _ = register_source(service.db, "a", "profile-edit", "학사 재학", "USER_CORRECTION")
    add_fact(service.db, "a", old.id, "profile", "education", {"text": "학사 재학"})
    current, _ = register_source(service.db, "a", "profile-edit", "학사 졸업", "USER_CORRECTION")
    fact = add_fact(service.db, "a", current.id, "profile", "education", {"text": "학사 졸업"})
    prep = preparation_context(service, workspace, [])
    assert [item["fact_id"] for item in prep["context"]["current_corrections"]] == [fact.id]
    assert old.id not in prep["source_ids"]


def test_current_manual_edit_available_but_regeneration_is_not_user_correction(flow):
    service, workspace, evidence = flow
    service.approve_strategy(workspace.id)
    q = question(service, workspace, evidence)
    original = service.artifact(workspace.id, "QuestionBrief", q["id"])
    edited = service.question_brief(workspace.id, q["id"], {**original.data, "primary_message": "평가 설계"})
    prep = preparation_context(service, workspace, service.selected([evidence.id]))
    assert prep["context"]["current_workspace_edits"][0]["artifact_id"] == edited.id
    assert edited.id not in prep["depends_on"]
    service.provider = Capture({**edited.data, "primary_message": "실험 설계"})
    service.question_brief(workspace.id, q["id"])
    assert not preparation_context(service, workspace, [])["context"]["current_workspace_edits"]
