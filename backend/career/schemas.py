from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompanyFact(Schema):
    statement: str
    source_id: str
    source_type: Literal["OFFICIAL", "EXTERNAL", "COMMUNITY", "USER_SUPPLIED"]
    published_at: str | None
    retrieved_at: str
    freshness: Literal["CURRENT", "DATED", "UNKNOWN"]


class Inference(Schema):
    text: str
    supporting_source_ids: list[str]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    is_inference: Literal[True] = True


class OutputImportance(Schema):
    output: str
    importance: Literal["CRITICAL", "CORE", "SUPPORTING"]


class JobRequirement(Schema):
    requirement: str
    source_id: str = "jd"


class OpportunityBrief(Schema):
    actual_outputs: list[str] = Field(min_length=1)
    base_profession: str
    specialty: str = ""
    tools: list[str] = []
    main_skills: list[str] = []
    differentiators: list[str] = []
    hiring_context: str = ""
    company_facts: list[CompanyFact] = []
    company_inferences: list[Inference] = []
    selection_process_signals: list[str] = []
    output_importance: list[OutputImportance] = []
    required: list[JobRequirement] = []
    preferred: list[JobRequirement] = []
    posting_status: Literal["OPEN", "CLOSED", "UNCERTAIN"] = "UNCERTAIN"
    deadline_at: str = ""
    deadline_timezone: str = ""
    posting_source: str = "jd"
    verified_at: str = ""


class EligibilityCheck(Schema):
    requirement: str
    status: Literal["MET", "NOT_MET", "NEEDS_VERIFICATION"]
    reason: str
    profile_keys: list[str] = []


class AxisAssessment(Schema):
    level: Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
    reason: str
    source_ids: list[str] = []


class OpportunityAssessment(Schema):
    eligibility: list[EligibilityCheck]
    fit: AxisAssessment
    career_value: AxisAssessment
    action_priority: AxisAssessment
    selection_risks: list[str]
    preparation_cost: Literal["NOW", "SHORT", "MEDIUM", "HIGH", "UNKNOWN"]
    recommendation: Literal["PROCEED", "PROCEED_WITH_GAP", "LOW_PRIORITY", "SKIP"]
    main_fix: str


class EvidenceItem(Schema):
    evidence_id: str
    job_output_id: str
    classification: Literal["DIRECT", "ADJACENT", "NO_EVIDENCE"]
    evidence_strength: Literal["STRONG", "MODERATE", "LIMITED", "NONE"]
    ownership_strength: Literal["STRONG", "MODERATE", "LIMITED", "NONE"]
    rationale: str
    skill_focus: Literal["MAIN_SKILL", "DIFFERENTIATOR", "UNSPECIFIED"] = "UNSPECIFIED"
    skill_name: str = ""
    concrete_output: str = ""
    understandable_hook: str = ""


class EvidencePack(Schema):
    items: list[EvidenceItem]
    uncovered_outputs: list[str]


class ApplicationBrief(Schema):
    positioning: str
    base_profession_identity: str
    main_skill_message: str
    differentiator_message: str = ""
    fatal_gaps: list[str] = []
    selection_risks: list[str] = []
    fatal_gap_strategy: str = ""
    assignment_statement: str
    do_not_position_as: list[str] = []
    question_portfolio: list[str] = []


class QuestionBrief(Schema):
    question_id: str
    question_type: Literal[
        "MOTIVATION", "JOB_COMPETENCY", "VALUES", "COLLABORATION", "CHALLENGE", "STRENGTH_WEAKNESS", "OTHER"
    ]
    evaluation_intent: str
    primary_message: str
    supporting_claims: list[str] = []
    evidence_ids: list[str] = Field(min_length=1)
    decision: str = ""
    insight: str = ""
    job_relevance: str = ""
    forbidden_claims: list[str] = []
    operational_value: str = ""
    value_scope: Literal["TECHNICAL_RESULT", "OPERATIONAL_POSSIBILITY", "MEASURED_BUSINESS_IMPACT"] = (
        "OPERATIONAL_POSSIBILITY"
    )
    expression_angle: str = ""


class Claim(Schema):
    text: str
    type: Literal["FACT", "METRIC", "OWNERSHIP", "INTERPRETATION"]
    evidence_ids: list[str]
    metric_ids: list[str] = []
    profile_fact_ids: list[str] = []
    company_source_ids: list[str] = []
    support: Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "NEEDS_REVIEW"]
    ownership_ok: bool


class Document(Schema):
    text: str
    claims: list[Claim]


class ReviewIssue(Schema):
    priority: Literal["P0", "P1", "P2", "P3"]
    code: str
    message: str


class Review(Schema):
    issues: list[ReviewIssue]
    followups: list[str]


class Patch(Schema):
    old_text: str
    new_text: str
    claims: list[Claim]
    issue_codes: list[str]


ResumeSectionKind = Literal["SUMMARY", "EXPERIENCE", "PROJECT", "EDUCATION", "SKILLS"]
RESUME_CHARACTER_BUDGET = {1: 3500, 2: 7000, "MASTER": 20000}


class ResumeSectionBudget(Schema):
    max_characters: int = Field(ge=1, le=20000)
    max_bullets: int = Field(ge=1, le=100)


class ResumeEvidenceRank(Schema):
    rank: int = Field(ge=1)
    evidence_id: str
    skill_focus: Literal["MAIN_SKILL", "DIFFERENTIATOR", "UNSPECIFIED"]
    skill_name: str = ""
    job_output_ids: list[str]
    output_importance: Literal["CRITICAL", "CORE", "SUPPORTING", "UNSPECIFIED"]
    classification: Literal["DIRECT", "ADJACENT"]
    evidence_strength: Literal["STRONG", "MODERATE", "LIMITED", "NONE"]
    ownership_strength: Literal["STRONG", "MODERATE", "LIMITED", "NONE"]
    concrete_output: str = ""
    understandable_hook: str = ""
    recency_date: str | None = None
    rationale: str


class ResumeBrief(Schema):
    target_role: str
    top_capabilities: list[str]
    project_order: list[str]
    selected_evidence_ids: list[str]
    page_budget: Literal[1, 2, "MASTER"] = 1
    bullet_intents: list[str]
    main_skills: list[str] = []
    differentiators: list[str] = []
    evidence_ranking: list[ResumeEvidenceRank] = []
    section_order: list[ResumeSectionKind] = ["SUMMARY", "PROJECT", "EXPERIENCE", "EDUCATION", "SKILLS"]
    section_budget: dict[ResumeSectionKind, ResumeSectionBudget] = {}

    @model_validator(mode="after")
    def layout_contract(self):
        if len(set(self.section_order)) != len(self.section_order):
            raise ValueError("이력서 섹션 순서가 중복됩니다.")
        if not set(self.section_budget) <= set(self.section_order):
            raise ValueError("이력서 섹션 예산과 섹션 순서를 일치시켜 주세요.")
        if sum(b.max_characters for b in self.section_budget.values()) > RESUME_CHARACTER_BUDGET[self.page_budget]:
            raise ValueError("섹션 예산 합계가 전체 이력서 문자 예산을 초과합니다.")
        if self.evidence_ranking:
            if [item.evidence_id for item in self.evidence_ranking] != self.selected_evidence_ids:
                raise ValueError("이력서 선택 근거와 근거 우선순위를 일치시켜 주세요.")
            if [item.rank for item in self.evidence_ranking] != list(range(1, len(self.evidence_ranking) + 1)):
                raise ValueError("이력서 근거 우선순위가 연속되어야 합니다.")
        return self


class ResearchSource(Schema):
    id: str
    url: str
    title: str
    published_at: str | None
    retrieved_at: str


class HistoricalJDSignal(Schema):
    statement: str
    source_id: str | None = None
    published_at: str | None = None
    retrieved_at: str | None = None
    date_label: str = "UNKNOWN"
    freshness: Literal["DATED", "UNKNOWN"] = "UNKNOWN"
    historical_only: Literal[True] = True

    @model_validator(mode="after")
    def dated(self):
        self.date_label = self.published_at or "UNKNOWN"
        self.freshness = "DATED" if self.published_at else "UNKNOWN"
        return self


class ResearchResult(Schema):
    official_facts: list[CompanyFact]
    external_evidence: list[CompanyFact]
    role_signals: list[str]
    historical_jd_signals: list[HistoricalJDSignal]
    selection_process_signals: list[str]
    inferences: list[Inference]
    sources: list[ResearchSource]

    @field_validator("historical_jd_signals", mode="before")
    @classmethod
    def preserve_legacy_notes(cls, value):
        # Old notes remain explicitly undated signals, never current company facts.
        return [{"statement": item} if isinstance(item, str) else item for item in value]

    @model_validator(mode="after")
    def validate_sources(self):
        sources = {source.id: source for source in self.sources}
        if len(sources) != len(self.sources):
            raise ValueError("조사 출처 ID가 중복됩니다.")
        if any(f.source_id not in sources for f in self.official_facts + self.external_evidence):
            raise ValueError("회사 사실에 등록된 조사 출처를 연결해 주세요.")
        if any(not set(i.supporting_source_ids) <= sources.keys() for i in self.inferences):
            raise ValueError("추론의 뒷받침 출처를 확인해 주세요.")
        for signal in self.historical_jd_signals:
            if signal.source_id:
                if signal.source_id not in sources:
                    raise ValueError("과거 공고 신호의 출처를 확인해 주세요.")
                source = sources[signal.source_id]
                signal.published_at = source.published_at
                signal.retrieved_at = source.retrieved_at
                signal.date_label = source.published_at or "UNKNOWN"
                signal.freshness = "DATED" if source.published_at else "UNKNOWN"
            elif signal.published_at:
                raise ValueError("날짜가 있는 과거 공고 신호에는 출처를 연결해 주세요.")
        return self
