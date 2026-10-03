# Cover Letter Composer — Implementation Spec

The full business/canonical source is copied under:
`source_specs/Career_Harness_Cover_Letter_Production_Spec_v1.2_FULL.md`

Implementation uses shared artifacts instead of one entity per conceptual step.

## Inputs

- OpportunityBrief
- EvidencePack
- ApplicationBrief
- application questions
- writing rules
- expression/style projections

## Process

### A. Application strategy
1. allocate question portfolio
2. avoid duplicate primary messages
3. derive question candidates/evidence
4. optionally require user approval

### B. Per question
1. classify intent
2. retrieve sanitized expression reference
3. retrieve/confirm factual evidence
4. create QuestionBrief
5. optionally require user approval
6. write draft
7. create ClaimLedger
8. run hard/semantic/ownership QA
9. tired recruiter review
10. conditional reverse interview
11. patch revision
12. enforce character limit
13. lock final

## Writing principles

General experience reasoning:
`Problem → Observation → Decision → Action → Evidence → Insight → Job Relevance`

Do not mechanically include every component.
Decision is usually the core.

Question skills:

- Motivation:
  personal criterion → why the base profession/industry → why company → company-specific fact → realistic growth

- Job competency:
  main skill → evidence → decision → result/metric → gap → job application

- Values:
  value → repeated decision rule → example → current behavior → workplace behavior

- Collaboration:
  common goal → disagreement/source → alignment → action → result

- Challenge:
  difficulty → initial approach → unexpected result → turning point → reframe → result → changed decision rule

## Portfolio QA

Across all answers:
- no duplicate primary message,
- no excessive repeated metric,
- repeated project must use a different role/angle,
- not every answer can be "AI/research",
- full application should communicate base profession + collaboration + values + specialty.

## Submission

Final cover letter answers are included in SubmissionBundle with:
- question brief versions,
- evidence ids,
- claim ledger,
- known gaps,
- protected final content.
