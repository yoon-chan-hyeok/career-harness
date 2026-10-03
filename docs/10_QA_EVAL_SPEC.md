# QA & Eval Specification

Eval is a first-class product component, not a later polish step.

## Baselines

Compare at minimum:

### B0 — Strong LLM only
JD + broad user context → answer.

### B1 — LLM + Retrieval
Relevant facts retrieved, no explicit strategy stage.

### B2 — Strategy + Writer
Opportunity/Application briefs before writing.

### B3 — Full workflow
Strategy + Writer + QA + patch revision.

Measure whether added stages actually help.

## Hard metrics

- canonical fact error
- unsupported metric
- ownership overclaim
- claim-boundary violation
- stale source use
- missing provenance
- character limit violation
- cross-user leak

## Product metrics

- Decision Acceptance Rate
- Evidence Replacement Rate
- Claim/Strategy rejection rate
- Final User Edit Distance
- first-draft acceptance
- revision count
- time-to-final
- cost/application
- reviewer over-correction rate

## Claim Ledger evaluation

Generated text is atomized into claims.
Validate every factual/metric/ownership claim.

## Stage evals

- OpportunityBrief accuracy
- EvidencePack relevance
- ApplicationBrief usefulness
- QuestionBrief acceptance
- Writer fidelity to locked message
- Recruiter usefulness
- Resume skimmability
- Postmortem attribution conservatism

## Historical dataset

Use actual correction cases:
- bad output
- user correction
- correction reason
- accepted output
- stage
- rule candidate

Never train/promote a rule only from one rejection outcome.

## Reviewer eval

Reviewer can fail too.

Measure:
- issue precision,
- whether its suggested change was accepted,
- whether accepted text was unnecessarily degraded.

## Regression policy

Any change to:
- prompt,
- model,
- retrieval,
- truth policy,
- review policy

runs relevant historical eval suites.
