# Resume Composer — Production / Implementation Spec

## Product purpose

Resume is not a portfolio or research narrative.

It is a fast-selection document that lets a recruiter infer:
- what the candidate can actually do,
- what outputs/results exist,
- how directly those outputs match the job.

Cover letter explains interpretation/decision.
Resume presents evidence.

## Canonical rules

1. Every bullet must stand alone.
2. Strongest result/output/function comes first.
3. Prefer understandable impact/function over research-only metrics.
4. Technology lists are secondary.
5. Include Decision/Constraint only when necessary to understand the value.
6. Do not make the reader reconstruct the whole project story.
7. Main Skill evidence appears before Differentiator.
8. JD-specific project order is allowed and expected.
9. Avoid traditional backend/production overclaim when evidence is limited.
10. Claim / Metric / Ownership rules are shared with Cover Letter.
11. Experience section should not repeat full project bullets; use it to clarify role/ownership.
12. A master resume may be comprehensive; company submission resumes are selective compilations.

## Pipeline

```text
OpportunityBrief
→ EvidencePack
→ ResumeBrief
→ project/evidence ranking
→ section selection
→ bullet compilation
→ skimmability QA
→ claim/ownership/metric QA
→ layout budget
→ final resume
```

## ResumeBrief

Contains:
- target_role
- main skills to prove
- differentiators to show after main skills
- project ordering
- section ordering
- selected evidence
- bullet intents
- target page budget

## Evidence ranking

Rank by:
1. Direct evidence for Main Skill
2. concrete output/result
3. ownership strength
4. relevance to actual job output
5. understandable hook
6. differentiator value
7. recency only as secondary tie-breaker

Do not rank projects by personal preference.

## Bullet compiler

Preferred shape:

`Impact / Output → Action → necessary Decision/Constraint → Evidence`

Examples of hook style:
- understandable function/result first
- methodology later

Avoid:
- starting with tool stacks
- starting with academic metric when a plain-language function is available
- paragraphs requiring previous bullet context

## Project section behavior

For each project:
- one-line purpose/output
- 2–4 bullets with distinct roles
- strongest evidence first
- do not repeat the same claim using different metrics
- negative result is valid if it demonstrates a decision/reframe

## Page/section budget

The logical composer should support:
- 1-page selective resume
- 2-page selective resume
- master resume

Layout rendering is a later adapter concern; content selection is core logic.

## Skimmability QA

Simulate 10–20 second scan:
- role identity clear?
- strongest evidence visible above fold/top section?
- bullets too research-heavy?
- output nouns visible?
- each bullet independently understandable?
- technology names obscuring value?
- main skill evidence visible before evaluation/reliability differentiators?

## Cross-document consistency

Resume and cover letter for the same application must share:
- canonical facts
- ownership
- metrics
- claim boundaries
- application positioning

They do NOT have to use identical wording.

## Resume claim ledger

Extract atomic claims and validate:
- metric scope
- ownership
- evidence
- project contribution boundary

No resume bullet can bypass Career Truth Core.
