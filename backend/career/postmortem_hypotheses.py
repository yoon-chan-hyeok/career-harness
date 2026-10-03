"""Optional model hypotheses anchored to a reconstructed submission, never causal facts."""

from typing import Literal

from pydantic import Field

from career.schemas import Schema


class Hypothesis(Schema):
    type: str
    observation: str
    confidence: Literal["LOW"]
    attribution_scope: Literal["DOCUMENT", "CODING", "INTERVIEW", "FINAL", "UNKNOWN"]
    supporting_artifact_ids: list[str] = Field(min_length=1)
    supporting_outcome_id: str
    validation_needed: str


class HypothesisDraft(Schema):
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=6)


def draft(service, data):
    allowed = set(data["supporting_artifact_ids"])
    value = service.ai(
        "postmortem",
        {
            "task": "Draft bounded hypotheses using ONLY this reconstructed submission and user-reported outcome. Never assert the cause of success/failure. Keep confidence LOW, match the outcome stage, cite exact allowed artifact and outcome IDs, and give concrete validation needed. Coding results cannot diagnose writing or propose writing rules. Missing submission is a limitation, not evidence about the actual submission. Return hypotheses only; no canonical facts or rules.",
            "reconstruction_mode": data["reconstruction_mode"],
            "reconstruction_warning": data["reconstruction_warning"],
            "jd": data["historical_jd"],
            "reverse_mapping": data["reverse_mapping"],
            "outcome": {
                "id": data["supporting_outcome_id"],
                "result": data["result"],
                "scope": data["attribution_scope"],
                "user_notes": data["user_notes"],
                "notes_authority": data["notes_authority"],
            },
            "allowed_artifact_ids": sorted(allowed),
        },
        HypothesisDraft,
    )
    for hypothesis in value["hypotheses"]:
        if hypothesis["attribution_scope"] != data["attribution_scope"]:
            raise ValueError("회고 가설은 해당 전형 단계 안에서만 검토할 수 있습니다.")
        if not set(hypothesis["supporting_artifact_ids"]) <= allowed:
            raise ValueError("회고 가설의 당시 자료 출처를 확인해 주세요.")
        if hypothesis["supporting_outcome_id"] != data["supporting_outcome_id"]:
            raise ValueError("회고 가설의 전형 결과 출처를 확인해 주세요.")
        if not hypothesis["observation"].strip() or not hypothesis["validation_needed"].strip():
            raise ValueError("가설 내용과 추가 확인 방법을 함께 기록해 주세요.")
    return [{**item, "origin": "MODEL_HYPOTHESIS_NOT_VERIFIED_CAUSE"} for item in value["hypotheses"]]
