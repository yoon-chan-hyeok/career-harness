# Implementation Plan v2.2 FINAL

Codex receives the whole repository at once but executes milestones sequentially.

`IMPLEMENTATION_STATUS.json` is updated after every milestone.

## M0 — Repository & infrastructure
Goal:
- backend/frontend workspace,
- Postgres+pgvector,
- migrations,
- lint/type/test,
- Docker Compose,
- minimal Workbench shell.

Task: `TASK-001`

## M1 — Smoke regression + production telemetry
Goal:
- existing small historical set as smoke regression,
- telemetry schema/storage from day one,
- no 30–50 case manual dataset requirement.

Task: `TASK-000`

## M2 — Career Truth Core
Goal:
- profile/fact/source/project/evidence/ownership/metric/claim-boundary/rule models,
- type-specific truth policies,
- verification/versioning.

Task: `TASK-002`

## M3 — Private corpus importer
Goal:
- available Genesis/master/project/application sources recursively,
- conflict reporting,
- service works with partially empty private_input.

Task: `TASK-003`

## M4 — Hybrid retrieval + Context Compiler
Goal:
- FTS + pgvector + metadata,
- Fact vs Expression separation,
- stage-specific context.

Task: `TASK-004`

## M5 — Company research + Opportunity Analyzer + minimal UI
Goal:
- pasted JD always works,
- OpenAI live web research when configured,
- source/freshness/inference separation,
- OpportunityBrief,
- EvidencePack,
- Opportunity/Job/Evidence UI slice.

Task: `TASK-005`

## M6 — Cover Letter single-question vertical slice + UI
Goal:
- ApplicationBrief,
- QuestionBrief,
- Claim lock,
- writer,
- ClaimLedger,
- QA,
- patch revision,
- first usable question UI.

Task: `TASK-006`

## M7 — Full Cover Letter Composer + UI
Goal:
- question portfolio,
- cross-question QA,
- character limits,
- strategy/claim gates,
- final cover-letter bundle.

Task: `TASK-007`

## M8 — Resume Composer + UI
Goal:
- evidence ranking,
- project selection,
- bullet compiler,
- skimmability QA,
- JD-specific ordering,
- structured content + Markdown/HTML preview.

Task: `TASK-008`

## M9 — Conversational Artifact Editing + state enforcement
Goal:
- natural-language corrections patch structured state,
- canonical state machine,
- stale propagation,
- assistant side panel behavior.

Task: `TASK-009`

## M10 — Submission Freeze + Interview Handoff
Goal:
- `SUBMISSION_FROZEN` distinct from actual `SUBMITTED`,
- immutable SubmissionBundle,
- explicit submission confirmation,
- separate InterviewHandoff artifact.

Task: `TASK-010`

## M11 — Outcome / Postmortem / Correction
Goal:
- stage-aware outcomes,
- conservative hypotheses,
- candidate rules without auto-promotion.

Task: `TASK-011`

## M12 — Production-derived eval hardening
Goal:
- stage eval,
- reviewer eval,
- baseline/ablation runner,
- use telemetry/corrections as they accumulate.

Task: `TASK-012`

## M13 — Jev shadow
Goal:
- bounded tasks only,
- disagreement/confidence/cost logging,
- no hard dependency.

Task: `TASK-013`

## M14 — MCP / auth / deployment / UI polish
Goal:
- production hardening,
- MCP adapter,
- auth/privacy,
- CI/observability,
- renderer/export adapters as needed.

Task: `TASK-014`

## Release target

`v0.1-personal` when M0–M10 pass.

M11–M14 harden learning, optimization, and production deployment.
