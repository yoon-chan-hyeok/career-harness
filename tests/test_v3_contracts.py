import pytest
from career.v3_contracts import (
    ContextBudget,
    RevisionRef,
    RoleInterpretationProposal,
    RuleTrace,
    SectionTrace,
)
from pydantic import ValidationError


def test_role_interpretations_share_fact_revision_without_changing_it():
    evidence = RevisionRef(kind="EVIDENCE", id="synthetic-evidence", revision="a" * 64, status="VERIFIED")
    original = evidence.model_dump()
    first = RoleInterpretationProposal(
        owner_id="alice", experience=evidence, base_profession="분석가", actual_output="분석 보고서",
        main_skill="분석", classification="DIRECT", interpretation="검증된 분석 경험",)
    second = RoleInterpretationProposal(
        owner_id="alice", experience=evidence, base_profession="개발자", actual_output="운영 서비스",
        main_skill="개발", classification="ADJACENT", interpretation="실험 코드 작성 경험",
        limitations=("서비스 운영 경험 미확인",),)
    assert first.experience == second.experience
    assert evidence.model_dump() == original
    with pytest.raises(ValidationError):
        RoleInterpretationProposal.model_validate({**first.model_dump(), "status": "APPROVED"})
    with pytest.raises(ValidationError):
        RoleInterpretationProposal.model_validate({**first.model_dump(), "classification": "NO_EVIDENCE"})


def test_selected_rule_does_not_become_a_passed_check():
    selected = RuleTrace(rule_id="synthetic-rule", rule_version="1", status="SELECTED", reason="문항에 해당")
    assert selected.validation_record_id is None
    for status in ("APPLIED", "CHECKED_PASS", "CHECKED_FAIL"):
        with pytest.raises(ValidationError):
            RuleTrace.model_validate({**selected.model_dump(), "status": status})
    checked = RuleTrace.model_validate({**selected.model_dump(), "status": "CHECKED_PASS",
                                       "validation_record_id": "actual-check-reference"})
    trace = SectionTrace(owner_id="alice", artifact_id="synthetic-doc", document_version=2,
                         section_id="paragraph-stable-id", text_sha256="b" * 64, claim_ids=("claim-id",),
                         evidence=(), rules=(checked,))
    assert trace.approval_event_id is None
    assert SectionTrace.model_validate_json(trace.model_dump_json()) == trace


@pytest.mark.parametrize("values,expected", [
    ({}, "NOT_ESTIMATED"),
    ({"input_tokens": 20, "input_limit": 100}, "NOT_ESTIMATED"),
    ({"input_tokens": 101, "input_limit": 100}, "EXCEEDED"),
    ({"input_tokens": 90, "output_tokens_reserved": 11, "context_limit": 100}, "EXCEEDED"),
    ({"input_tokens": 90, "output_tokens_reserved": 10, "context_limit": 100}, "WITHIN_STATIC_BUDGET"),
    ({"input_tokens": 90, "output_tokens_reserved": 10, "context_limit": 100, "input_limit": 89}, "EXCEEDED"),
])
def test_static_budget_is_conservative_and_reserves_output(values, expected):
    budget = ContextBudget.model_validate(values)
    assert budget.verdict() == expected


@pytest.mark.parametrize("value", [-1, True, 1.5, "100"])
def test_token_measurements_reject_invalid_types(value):
    with pytest.raises(ValidationError):
        ContextBudget(input_tokens=value)
