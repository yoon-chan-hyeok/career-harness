# ruff: noqa: F811 -- reusable pytest fixture
from copy import deepcopy

from career.domain import save_entity
from career.interview_defense import build_handoff, speaking_notes
from test_workflow import finish, flow  # noqa: F401 -- pytest fixture


def test_handoff_preserves_frozen_metric_scope_and_unknown_ownership(flow):
    f, w, e = flow
    e.data = {**e.data, "ownership": {"implementation": "USER_AI_ASSISTED"}}
    metric = save_entity(
        f.db,
        f.user,
        "Metric",
        {
            "source_id": e.source_id,
            "evidence_id": e.id,
            "name": "정확도",
            "value": "80",
            "unit": "%",
            "dataset": "검증 데이터",
            "subset": "검증 부분집합",
            "experiment_version": "v1",
            "baseline": "70",
            "denominator": "100",
            "valid_for_claims": ["검증 부분집합 정확도"],
            "invalid_for_claims": ["전체 운영 정확도"],
            "status": "VERIFIED",
            "measurement_context": "EXPERIMENT",
            "business_effect": False,
        },
        True,
    )
    previous = f.artifact(w.id, "EvidencePack", current=False).data
    fields = {
        "evidence_id",
        "job_output_id",
        "classification",
        "evidence_strength",
        "ownership_strength",
        "rationale",
    }
    f.map_evidence(
        w.id,
        {
            "items": [{k: v for k, v in item.items() if k in fields} for item in previous["items"]],
            "uncovered_outputs": [],
        },
    )
    f.strategy(w.id, f.artifact(w.id, "ApplicationBrief", current=False).data)
    q = finish(f, w, e)
    document = f.artifact(w.id, "Draft", q["id"])
    f.update_ledger(w.id, q["id"], [{**c, "metric_ids": [metric.id]} for c in document.data["claims"]])
    f.review(w.id, q["id"], manual_verified=True)
    f.final_lock(w.id, q["id"])
    from final_review_fixture import confirm_final

    confirm_final(f, w.id)
    f.ready(w.id)
    bundle = f.freeze(w.id)
    frozen = deepcopy(bundle.data)
    metric.data = {**metric.data, "value": "90", "dataset": "나중 데이터"}
    e.data = {**e.data, "ownership": {"implementation": "USER"}}
    handoff = f.handoff(w.id)
    note = handoff.data["metric_scope_notes"][0]["metrics"][0]
    assert note["value"] == "80" and note["dataset"] == "검증 데이터"
    assert note["subset"] == "검증 부분집합" and note["denominator"] == "100"
    assert note["measurement_context"] == "EXPERIMENT" and not note["business_effect"]
    defense = handoff.data["claim_defense"][0]
    assert defense["document_id"] == f.artifact(w.id, "Draft", q["id"]).id
    assert defense["defense_evidence"][0]["metrics"][0]["metric_id"] == metric.id
    roles = handoff.data["ownership_notes"][0]
    assert roles["ownership"]["implementation"] == "USER_AI_ASSISTED"
    assert "problem_definition" in roles["missing_information"]
    assert bundle.data == frozen


def test_missing_metric_scope_is_explicit_and_gap_answers_do_not_invent_plans():
    evidence = {
        "id": "e",
        "source_id": "s",
        "title": "측정",
        "body": "정확도 80%를 관찰했습니다.",
        "data": {},
    }
    bundle = {
        "company": "Company",
        "role": "Analyst",
        "evidence": [evidence],
        "artifacts": [
            {
                "id": "strategy",
                "version": 1,
                "kind": "ApplicationBrief",
                "data": {"fatal_gaps": ["운영 배포"], "fatal_gap_strategy": "먼저 업무를 배운다"},
            },
            {
                "id": "draft",
                "version": 2,
                "kind": "Draft",
                "slot": "q",
                "data": {"claims": [{"text": evidence["body"], "evidence_ids": ["e"], "metric_ids": []}]},
            },
        ],
    }
    content = build_handoff(bundle, "bundle")
    assert content["metric_scope_notes"][0]["metrics"] == []
    assert "dataset" in content["metric_scope_notes"][0]["missing_information"]
    gap = content["fatal_gap_answers"][0]
    assert gap["frozen_strategy_quote"] == "먼저 업무를 배운다"
    assert "confirmed_learning_plan" in gap["missing_information"]
    assert "직접 수행했다고 주장하지" in gap["safe_answer"]
    assert content["claim_defense"][0]["defense_evidence"][0]["source_quote"] == evidence["body"]


def test_different_speaking_structures_use_frozen_negative_result_and_flag_timing():
    evidence = {
        "id": "e",
        "source_id": "s",
        "title": "실패 실험",
        "body": "가설을 줄였습니다.",
        "data": {
            "ownership": {"implementation": "TEAM"},
            "forbidden_claims": ["단독 구현"],
            "decision_episode": {
                "situation": "예외 사례",
                "constraint": "검증 범위 제한",
                "hypothesis": "개선 가능성",
                "options": ["대안 A", "대안 B"],
                "observation": "일부에서 실패",
                "unexpected_result": "예상과 달랐음",
                "reframe": "주장을 축소",
                "decision": "대안 B로 확인",
                "action": "제한된 범위 실험",
                "experiment": "실험 기록",
                "outcome": "적용 한계 확인",
                "lesson": "범위를 먼저 대조",
            },
        },
    }
    plans = speaking_notes(evidence)
    assert [plans[key]["target_seconds"] for key in ("one_minute", "three_minute", "five_minute")] == [
        60,
        180,
        300,
    ]
    assert all(plan["timing_status"] == "NOT_MEASURED_PRACTICE_REQUIRED" for plan in plans.values())
    assert "대안 A; 대안 B" in plans["five_minute"]["text"]
    assert "주장을 축소" in plans["five_minute"]["text"]
    assert "단독 구현" in plans["five_minute"]["forbidden_claims"]
    assert plans["one_minute"]["structure"] != plans["five_minute"]["structure"]
