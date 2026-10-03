# Domain Model — v2.2 FINAL

## Career Truth entities

### User
- id
- created_at

### Source
- id
- user_id
- source_type
- title
- authority_class
- verification_status
- valid_from / valid_to
- created_at
- external_ref

### CareerFact
- id
- user_id
- fact_type
- key
- value_json
- source_id
- status
- effective_at
- supersedes_id

### Project
- id
- user_id
- name
- summary
- status

### Evidence
- id
- project_id nullable
- evidence_type
- title
- body
- source_id
- verification_status

### DecisionEpisode
- situation
- constraint
- observation
- options
- decision
- action
- outcome
- lesson

Optional research fields:
- hypothesis
- experiment
- unexpected_result
- reframe

### Metric
- name
- value
- unit
- dataset
- subset
- experiment_version
- baseline
- denominator
- source_id
- valid_for_claims_json
- invalid_for_claims_json

### Ownership
- problem_definition
- hypothesis
- experiment_design
- implementation
- integration
- result_scope

Values:
- USER
- USER_AI_ASSISTED
- USER_MODIFIED_EXISTING_CODE
- TEAM
- LAB
- UNKNOWN

### ClaimBoundary
- entity/project scope
- forbidden_claim
- safe_claim
- rationale
- source_id

### WritingRule
- scope_type
- scope_value
- rule_type
- rule
- status
- source_case_ids

### ExpressionRecord
- user_id
- question_type
- industry nullable
- company nullable
- accepted_text
- rejected_text nullable
- logic_pattern_json
- tone_tags_json
- source_id
- status

### CapabilityRecord
Evidence-backed qualitative profile only.
- user_id
- capability_name
- status: STRONG | MODERATE | LIMITED | NONE
- evidence_ids
- gap_evidence_ids
- updated_at

No uncalibrated numeric confidence score.

---

## Opportunity entities

### Opportunity
- company
- role
- jd_raw
- jd_source
- deadline
- status

### CompanyResearchResult
- opportunity_id
- retrieved_at
- official_facts_json
- external_evidence_json
- role_signals_json
- historical_jd_signals_json
- selection_process_signals_json
- inferences_json
- sources_json

### OpportunityEvidenceMap
Relationship:
`job_output × evidence`
- DIRECT / ADJACENT / NO_EVIDENCE
- evidence_strength ordinal
- ownership_strength ordinal
- rationale

---

## Application entities

### ApplicationWorkspace
- opportunity_id
- state
- strategy_version
- submission_snapshot_id nullable

### ApplicationQuestion
- text
- question_type
- character_limit
- state

### DraftVersion
- content
- version
- source_question_brief_version
- protected_spans_json

### SubmissionSnapshot / SubmissionBundle
- frozen application content
- frozen_at
- submitted_at nullable
- immutable after freeze

### InterviewHandoffRecord
- submission_bundle_id
- generated content/version
- depends_on immutable submission bundle

### SelectionOutcome
- stage
- result
- date
- known_reason nullable
- notes

### PostmortemHypothesis
- type
- observation
- confidence ordinal
- attribution_scope
- supporting_artifact_ids

---

## Telemetry entities

### ArtifactFeedbackEvent
Captures real user feedback for production-derived eval.

- id
- user_id
- application_id
- question_id nullable
- artifact_id
- artifact_version
- stage
- action: ACCEPT | EDIT | REJECT | SKIP
- edit_type nullable
- before_json/text nullable
- after_json/text nullable
- created_at

### DocumentRevisionEvent
- id
- user_id
- application_id
- question_id nullable
- document_type
- from_version
- to_version
- diff_summary_json
- edit_distance nullable
- reviewer_issue_ids
- created_at

---

## Artifact metadata

Every major generated artifact:
- artifact_id
- type
- version
- status
- depends_on
- created_at
- prompt_version
- model_version
- source_ids

Statuses:
- ACTIVE
- LOCKED
- STALE
- SUPERSEDED
- INVALID
