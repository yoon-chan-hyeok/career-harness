# TASK-005 — Company Research + Opportunity Analyzer + Minimal UI

Read:
- `docs/06A_WEB_RESEARCH_SPEC.md`
- `docs/06_TRUTH_RETRIEVAL_SPEC.md`
- `docs/04_ARTIFACT_SCHEMAS.md`

## Research

Implement:
- CompanyResearchProvider
- ManualResearchProvider
- FakeResearchProvider
- OpenAIWebResearchProvider when configured

No live credential:
- manual/JD-only mode still fully usable.

Persist:
- official facts
- external evidence
- historical role signals
- selection process signals
- inference
- sources/freshness

Raw external content is untrusted.

## Opportunity artifacts

Create `OpportunityBrief` with company/job-side analysis only:
- Actual Output
- Base Profession
- Specialty/Tool
- Main Skill
- Differentiator
- Hiring context
- company facts/inferences

Then create `EvidencePack`:
- Direct/Adjacent/No Evidence
- evidence/ownership strength
- verification
- claim boundaries

Do NOT place candidate fatal gaps or assignment statement inside OpportunityBrief.

Those belong to ApplicationBrief in TASK-006.

## Minimal UI

Implement usable Fit/Job/Evidence views:
- current opportunity
- job analysis
- sources
- evidence mapping
- patch classification action

Acceptance:
- pasted JD works without live research
- live provider failure falls back
- fact/inference separated
- sources preserved
- UI shows analysis/evidence
- no final writing yet
