# ruff: noqa: F811 -- pytest fixture imported for reuse
import json

import pytest
from career.db import Record
from career.domain import save_entity
from career.models import Artifact, Feedback
from career.promotion import direct_preference, evaluate_candidate, promote_candidate, usable_rule
from career.providers import FakeLLMProvider
from career.truth import register_source
from test_workflow import finish, flow  # noqa: F401 -- pytest fixture


def test_model_postmortem_is_optional_and_bounded_to_current_stage_and_snapshot(flow):
    f, ws, _ = flow
    f.outcome(ws.id, "CODING_FAIL", "시간 안에 완성하지 못함")
    recorded = f.postmortem(ws.id)
    hypothesis = {
        "type": "TIME_ALLOCATION", "observation": "시간 배분을 추가 확인해야 합니다.",
        "confidence": "LOW", "attribution_scope": "CODING",
        "supporting_artifact_ids": recorded.data["supporting_artifact_ids"][:1],
        "supporting_outcome_id": recorded.data["supporting_outcome_id"],
        "validation_needed": "당시 풀이 기록과 시간 배분을 확인합니다.",
    }
    f.provider = FakeLLMProvider({"postmortem": {"hypotheses": [hypothesis]}})
    result = f.postmortem(ws.id, draft_hypotheses=True)
    assert result.data["hypothesis_mode"] == "MODEL_DRAFT_WITH_RECORDED_OBSERVATIONS"
    assert result.data["writing_rule_updated"] is False
    assert result.data["candidate_rules"] == []
    assert result.data["hypotheses"][-1]["origin"] == "MODEL_HYPOTHESIS_NOT_VERIFIED_CAUSE"
    hypothesis["attribution_scope"] = "DOCUMENT"
    with pytest.raises(ValueError, match="전형 단계"):
        f.postmortem(ws.id, draft_hypotheses=True)
    hypothesis["attribution_scope"] = "CODING"
    hypothesis["supporting_artifact_ids"] = ["made-up"]
    with pytest.raises(ValueError, match="당시 자료"):
        f.postmortem(ws.id, draft_hypotheses=True)


def candidate(db, count=2, user="a"):
    source, _ = register_source(db, user, "rules", "판단을 앞에 쓴다", "USER_OBSERVATION")
    ids = []
    for n in range(count):
        artifact = Artifact(
            user_id=user,
            workspace_id=f"workspace-{n}",
            kind="Draft",
            slot="",
            version=1,
            data={"text": f"판단 {n}", "claims": []},
            depends_on=[],
            source_ids=[],
        )
        db.add(artifact)
        db.flush()
        event = Feedback(
            user_id=user,
            application_id=artifact.workspace_id,
            artifact_id=artifact.id,
            artifact_version=artifact.version,
            stage="Draft",
            action="EDIT",
            data={"before": {"text": f"과정 {n}"}, "after": artifact.data, "edit_type": "USER_EDIT"},
        )
        db.add(event)
        db.flush()
        ids.append(event.id)
    item = save_entity(
        db,
        user,
        "WritingRule",
        {
            "source_id": source.id,
            "scope_type": "USER",
            "scope_value": user,
            "rule_type": "CORRECTION_LEARNING",
            "rule": "판단을 앞에 배치",
            "source_case_ids": ids,
        },
    )
    return item


class TrialProvider:
    def __init__(self, reject=False):
        self.calls = []
        self.reject = reject
        self.last_trace = {"model": "fixture-trial-only", "cost": 0}

    def structured(self, stage, context, schema):
        self.calls.append((stage, context))
        if stage == "rule_regression_writer":
            expected = context["confirmed_historical_answer"]
            return schema.model_validate(
                {"answer": expected if isinstance(expected, str) else json.dumps(expected)}
            )
        return schema.model_validate(
            {"passed": not self.reject, "reason": "Actual fixture execution, not a production quality claim"}
        )


def test_no_confirmation_only_or_candidate_skip_promotion(db):
    rule = candidate(db)
    with pytest.raises((ValueError, LookupError)):
        save_entity(
            db,
            "a",
            "WritingRule",
            {**{k: v for k, v in rule.data.items() if k != "version"}, "status": "CANONICAL"},
            True,
        )
    assert rule.status == "CANDIDATE"


def test_single_case_and_coding_outcome_are_not_learning_evidence(db):
    rule = candidate(db, 1)
    with pytest.raises(ValueError, match="두 건"):
        evaluate_candidate(db, "a", rule.id, TrialProvider())
    coding = Record(user_id="a", kind="SelectionOutcome", data={"result": "CODING_FAIL"})
    db.add(coding)
    db.flush()
    rule.data = {**rule.data, "source_case_ids": [coding.id]}
    with pytest.raises(ValueError, match="코딩"):
        evaluate_candidate(db, "a", rule.id, TrialProvider())


def test_actual_historical_run_and_explicit_approval_are_required(db):
    rule = candidate(db)
    provider = TrialProvider()
    evaluation = evaluate_candidate(db, "a", rule.id, provider)
    assert evaluation["data"]["status"] == "PASSED"
    assert evaluation["data"]["checks_executed"] == 10
    assert len(provider.calls) == 20
    assert all(c[1]["rule"]["rule"] == rule.data["rule"] for c in provider.calls)
    with pytest.raises(ValueError, match="승인"):
        promote_candidate(db, "a", rule.id, evaluation["id"])
    promoted = promote_candidate(db, "a", rule.id, evaluation["id"], True)
    assert promoted["status"] == "CANONICAL" and rule.status == "SUPERSEDED"
    assert usable_rule(db, "a", promoted["data"])


def test_failed_run_cannot_be_promoted(db):
    rule = candidate(db)
    evaluation = evaluate_candidate(db, "a", rule.id, TrialProvider(reject=True))
    with pytest.raises(ValueError, match="검증"):
        promote_candidate(db, "a", rule.id, evaluation["id"], True)
    assert rule.status == "CANDIDATE"


def test_evaluation_is_version_and_case_bound_and_user_scoped(db):
    rule = candidate(db)
    evaluation = evaluate_candidate(db, "a", rule.id, TrialProvider())
    with pytest.raises(LookupError):
        promote_candidate(db, "b", rule.id, evaluation["id"], True)
    event = db.get(Feedback, rule.data["source_case_ids"][0])
    assert event is not None
    event.data = {**event.data, "after": {"text": "바뀐 교정"}}
    with pytest.raises(ValueError, match="버전"):
        promote_candidate(db, "a", rule.id, evaluation["id"], True)


def test_changed_rule_version_and_forged_directive_are_rejected(db):
    rule = candidate(db)
    evaluation = evaluate_candidate(db, "a", rule.id, TrialProvider())
    rule.data = {**rule.data, "rule": "다른 규칙"}
    with pytest.raises(ValueError, match="버전"):
        promote_candidate(db, "a", rule.id, evaluation["id"], True)
    data = {k: v for k, v in rule.data.items() if k != "version"}
    with pytest.raises(ValueError, match="개인 선호"):
        save_entity(db, "a", "WritingRule", {**data, "origin": "USER_DIRECTIVE", "status": "CANONICAL"}, True)


def test_explicit_user_preference_is_separate_from_learning(db):
    with pytest.raises(ValueError):
        direct_preference(db, "a", "짧게 쓴다")
    preference = direct_preference(db, "a", "짧게 쓴다", confirmed=True)
    assert preference["data"]["source_case_ids"] == []
    assert preference["data"]["origin"] == "USER_DIRECTIVE"
    assert usable_rule(db, "a", preference["data"])
    with pytest.raises(ValueError, match="전체 사용자"):
        direct_preference(db, "a", "짧게 쓴다", scope_type="GLOBAL", confirmed=True)  # type: ignore[reportArgumentType]


def test_postmortem_maps_exact_frozen_evidence_and_not_later_jd(flow):
    f, w, e = flow
    finish(f, w, e)
    f.ready(w.id)
    bundle = f.freeze(w.id)
    w.jd_raw = "현재는 완전히 다른 직무"
    f.outcome(w.id, "DOCUMENT_FAIL", "명확하지 않았다는 메모")
    result = f.postmortem(w.id)
    assert result.depends_on == [bundle.id]
    assert result.data["historical_jd"] == bundle.data["jd"]
    assert result.data["reverse_mapping"]["claims"][0]["claim"]["evidence_ids"] == [e.id]
    assert result.data["reverse_mapping"]["job_outputs"][0]["evidence"][0]["classification"] == "DIRECT"
    assert result.data["supporting_artifact_ids"] and result.data["known_reason"] is None
    assert all(h["confidence"] == "LOW" for h in result.data["hypotheses"])


def test_postmortem_marks_missing_submission_and_respects_coding_scope(flow):
    f, w, _ = flow
    f.outcome(w.id, "CODING_FAIL", "코드 작성 시간 부족")
    result = f.postmortem(w.id)
    assert result.data["reconstruction_mode"] == "CURRENT_RECORDS_SUBMISSION_NOT_RECONSTRUCTABLE"
    assert result.data["reconstruction_warning"]
    assert result.data["candidate_rules"] == []
    assert result.data["attribution_scope"] == "CODING" and not result.data["writing_rule_updated"]
