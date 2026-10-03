"""Validated auxiliary Career Truth entities stored in user-scoped domain records."""

from typing import Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from career.artifacts import stale
from career.entities import ENTITY_MODELS
from career.models import Evidence, Source
from career.schemas import Schema
from career.truth import owned

OwnershipValue = Literal["USER", "USER_AI_ASSISTED", "USER_MODIFIED_EXISTING_CODE", "TEAM", "LAB", "UNKNOWN"]
Verification = Literal[
    "VERIFIED", "USER_CONFIRMED", "SOURCE_BACKED", "UNVERIFIED", "CONFLICTED", "SUPERSEDED", "DO_NOT_USE"
]


class Project(Schema):
    name: str
    summary: str
    source_id: str
    status: Verification = "UNVERIFIED"
    implementation_status: Literal[
        "UNKNOWN", "IMPLEMENTED", "EXPERIMENT_VERIFIED", "PARTIAL_EXPLORATORY", "DESIGN_IDEA", "NOT_DONE"
    ] = "UNKNOWN"


class DecisionEpisode(Schema):
    source_id: str
    evidence_id: str
    situation: str
    constraint: str
    observation: str
    options: list[str]
    decision: str
    action: str
    outcome: str
    lesson: str
    hypothesis: str = ""
    experiment: str = ""
    unexpected_result: str = ""
    reframe: str = ""
    rejected_hypothesis: str = ""
    reduced_claim: str = ""
    validation: str = ""
    limitation: str = ""
    outcome_kind: Literal["POSITIVE", "NEGATIVE", "INCONCLUSIVE", "UNKNOWN"] = "UNKNOWN"


class Metric(Schema):
    source_id: str
    evidence_id: str
    name: str
    value: str
    unit: str
    dataset: str
    subset: str
    experiment_version: str
    baseline: str | None
    denominator: str | None
    valid_for_claims: list[str]
    invalid_for_claims: list[str]
    status: Verification = "UNVERIFIED"
    measurement_context: Literal["UNKNOWN", "EXPERIMENT", "PROTOTYPE", "PRODUCTION"] = "UNKNOWN"
    measured_at: str = ""
    business_effect: bool = False


class Ownership(Schema):
    source_id: str
    evidence_id: str
    problem_definition: OwnershipValue = "UNKNOWN"
    hypothesis: OwnershipValue = "UNKNOWN"
    experiment_design: OwnershipValue = "UNKNOWN"
    implementation: OwnershipValue = "UNKNOWN"
    integration: OwnershipValue = "UNKNOWN"
    result_scope: OwnershipValue = "UNKNOWN"


class ClaimBoundary(Schema):
    source_id: str
    evidence_id: str
    forbidden_claim: str = Field(min_length=1)
    safe_claim: str
    rationale: str


class WritingRule(Schema):
    source_id: str
    scope_type: Literal["GLOBAL", "USER", "INDUSTRY", "ROLE_TYPE", "QUESTION_TYPE", "PROJECT", "COMPANY"]
    scope_value: str
    rule_type: str
    rule: str
    status: Literal["CANDIDATE", "VERIFIED", "CANONICAL"] = "CANDIDATE"
    source_case_ids: list[str] = []
    domain: Literal["COMMON", "COVER", "RESUME", "OPPORTUNITY"] = "COMMON"
    origin: Literal["LEARNED", "USER_DIRECTIVE"] = "LEARNED"
    candidate_id: str = ""
    evaluation_id: str = ""


class ExpressionRecord(Schema):
    source_id: str
    question_type: str
    industry: str | None = None
    company: str | None = None
    accepted_text: str
    rejected_text: str | None = None
    logic_pattern: list[str] = []
    tone_tags: list[str] = []


class CapabilityRecord(Schema):
    capability_name: str
    status: Literal["STRONG", "MODERATE", "LIMITED", "NONE"]
    evidence_ids: list[str]
    gap_evidence_ids: list[str] = []


SCHEMAS = {
    model.__name__: model
    for model in (
        Project,
        DecisionEpisode,
        Metric,
        Ownership,
        ClaimBoundary,
        WritingRule,
        ExpressionRecord,
        CapabilityRecord,
    )
}


def save_entity(db: Session, user: str, kind: str, payload: dict, explicit_confirmation=False):
    if kind not in SCHEMAS:
        raise ValueError("지원하지 않는 근거 항목입니다.")
    data = SCHEMAS[kind].model_validate(payload).model_dump()
    model = ENTITY_MODELS[kind]
    if "source_id" in data:
        source = owned(db, Source, user, data["source_id"])
        if source.status not in {"VERIFIED", "SOURCE_BACKED", "USER_CONFIRMED"}:
            raise ValueError("유효한 출처가 필요합니다.")
        if source.authority == "REFERENCE" and kind in {
            "Project",
            "DecisionEpisode",
            "Metric",
            "Ownership",
            "ClaimBoundary",
        }:
            raise ValueError("규칙·표현 참고 자료는 개인 사실의 출처가 될 수 없습니다.")
    if kind == "WritingRule" and data["status"] != "CANDIDATE" and not explicit_confirmation:
        raise ValueError("작성 규칙 승격은 명시적 승인이 필요합니다.")
    if kind == "WritingRule" and data["status"] != "CANDIDATE":
        from career.promotion import validate_promotion

        validate_promotion(db, user, data)
    if kind == "Ownership" and not explicit_confirmation:
        raise ValueError("수행 범위 변경은 직접 확인이 필요합니다.")
    evidence = owned(db, Evidence, user, data["evidence_id"]) if "evidence_id" in data else None
    for ident in data.get("evidence_ids", []) + data.get("gap_evidence_ids", []):
        owned(db, Evidence, user, ident)
    if evidence:
        previous = [
            r
            for r in db.scalars(select(model).where(model.user_id == user))
            if r.data.get("evidence_id") == evidence.id and r.data.get("status") != "SUPERSEDED"
        ]
        data["version"] = max([r.data.get("version", 1) for r in previous] or [0]) + 1
        for old in previous:
            if kind != "Metric" or old.data.get("name") == data.get("name"):
                old.data = {**old.data, "status": "SUPERSEDED"}
                old.status = "SUPERSEDED"
        stale(db, user, [evidence.source_id])
        if kind == "Ownership":
            evidence.data = {
                **evidence.data,
                "ownership": {
                    k: data[k]
                    for k in [
                        "problem_definition",
                        "hypothesis",
                        "experiment_design",
                        "implementation",
                        "integration",
                        "result_scope",
                    ]
                },
            }
        elif kind == "ClaimBoundary":
            evidence.data = {
                **evidence.data,
                "forbidden_claims": [*evidence.data.get("forbidden_claims", []), data["forbidden_claim"]],
            }
        elif kind == "Metric":
            evidence.data = {
                **evidence.data,
                "metric_ledger": [
                    {**metric, "status": "SUPERSEDED"} if metric.get("name") == data["name"] else metric
                    for metric in evidence.data.get("metric_ledger", [])
                ]
                + [data],
            }
        elif kind == "DecisionEpisode":
            evidence.data = {**evidence.data, "decision_episode": data}
    if evidence is None and data.get("source_id"):
        previous = [
            r
            for r in db.scalars(
                select(model).where(model.user_id == user, model.source_id == data["source_id"])
            )
            if r.status != "SUPERSEDED"
            and all(
                r.data.get(k) == data.get(k)
                for k in (["scope_type", "scope_value", "rule_type"] if kind == "WritingRule" else ["name"])
            )
        ]
        data["version"] = max([r.version for r in previous] or [0]) + 1
        for old in previous:
            old.status = "SUPERSEDED"
            old.data = {**old.data, "status": "SUPERSEDED"}
        if previous:
            stale(db, user, [data["source_id"]])
    record = model(
        user_id=user,
        data=data,
        source_id=data.get("source_id"),
        evidence_id=data.get("evidence_id"),
        version=data.get("version", 1),
        status=data.get("status", "USER_CONFIRMED" if explicit_confirmation else "UNVERIFIED"),
    )
    db.add(record)
    db.flush()
    if kind == "DecisionEpisode":
        from career.decision_graph import project_episode

        project_episode(db, user, record.id)
    elif evidence is not None and kind in {"Ownership", "Metric", "ClaimBoundary"}:
        from career.decision_graph import invalidate_graphs

        invalidate_graphs(db, user, evidence_ids={evidence.id})
    return record
