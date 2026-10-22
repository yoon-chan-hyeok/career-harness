"""Versioned v3 read models. These contracts grant no approval or execution authority."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
TokenCount = Annotated[int, Field(strict=True, ge=0)]
CONTRACT_VERSION = "v3-preview-1"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RevisionRef(Contract):
    kind: Literal["SOURCE", "EVIDENCE", "FACT", "DECISION_EPISODE", "OWNERSHIP", "METRIC", "CLAIM_BOUNDARY"]
    id: Identifier
    revision: Digest
    status: Identifier


class ExperienceCard(Contract):
    """Projection over one existing Evidence; never a second editable Fact store."""

    contract_version: Literal["v3-preview-1"] = CONTRACT_VERSION
    owner_id: Identifier
    experience_id: Identifier
    revision: Digest
    title: str
    body: str
    evidence: RevisionRef
    source: RevisionRef
    related_sources: tuple[RevisionRef, ...] = ()
    records: tuple[RevisionRef, ...] = ()
    warnings: tuple[str, ...] = ()
    mode: Literal["READ_ONLY_PROJECTION"] = "READ_ONLY_PROJECTION"


class RoleInterpretationProposal(Contract):
    """Future proposal format; semantic grounding and user selection remain separate."""

    owner_id: Identifier
    experience: RevisionRef
    base_profession: Identifier
    actual_output: Identifier
    main_skill: Identifier
    classification: Literal["DIRECT", "ADJACENT", "NO_EVIDENCE"]
    interpretation: str = Field(min_length=1)
    limitations: tuple[str, ...] = ()
    status: Literal["PROPOSED"] = "PROPOSED"

    @model_validator(mode="after")
    def evidence_reference(self):
        if self.experience.kind != "EVIDENCE":
            raise ValueError("직무 해석은 현재 경험 근거의 버전을 참조해야 합니다.")
        if self.classification == "NO_EVIDENCE" and not self.limitations:
            raise ValueError("근거가 없는 해석은 부족한 범위를 명시해야 합니다.")
        return self


class RuleTrace(Contract):
    rule_id: Identifier
    rule_version: Identifier
    status: Literal["SELECTED", "SENT", "CHECKED_PASS", "CHECKED_FAIL", "NOT_APPLICABLE", "BLOCKED"]
    reason: str = Field(min_length=1)
    validation_record_id: Identifier | None = None

    @model_validator(mode="after")
    def check_proof(self):
        if self.status.startswith("CHECKED_") and self.validation_record_id is None:
            raise ValueError("규칙 검사 결과에는 실제 검사 기록이 필요합니다.")
        if not self.status.startswith("CHECKED_") and self.validation_record_id is not None:
            raise ValueError("선택·전달·보류와 검사 결과를 구분해 주세요.")
        return self


class SectionTrace(Contract):
    """Persistable contract only; this preview does not invent traces for legacy prose."""

    owner_id: Identifier
    artifact_id: Identifier
    document_version: Annotated[int, Field(strict=True, ge=1)]
    section_id: Identifier
    text_sha256: Digest
    claim_ids: tuple[Identifier, ...]
    evidence: tuple[RevisionRef, ...]
    rules: tuple[RuleTrace, ...] = ()
    approval_event_id: Identifier | None = None


class ContextBudget(Contract):
    """Static request-size check, not a provider quota, price or live availability claim."""

    input_tokens: TokenCount | None = None
    output_tokens_reserved: TokenCount | None = None
    context_limit: Annotated[int, Field(strict=True, ge=1)] | None = None
    input_limit: Annotated[int, Field(strict=True, ge=1)] | None = None

    def verdict(self) -> Literal["NOT_ESTIMATED", "WITHIN_STATIC_BUDGET", "EXCEEDED"]:
        if self.input_tokens is None:
            return "NOT_ESTIMATED"
        if self.input_limit is not None and self.input_tokens > self.input_limit:
            return "EXCEEDED"
        if self.output_tokens_reserved is None or self.context_limit is None:
            return "NOT_ESTIMATED"
        if self.input_tokens + self.output_tokens_reserved > self.context_limit:
            return "EXCEEDED"
        return "WITHIN_STATIC_BUDGET"
