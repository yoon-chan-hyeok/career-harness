# Codex Master Instruction — One-Shot Build v2.2 FINAL

You are implementing the Career Harness described by this repository.

The user wants to provide this repository once and have you carry the implementation through
without requiring a new prompt for every task.

## First action — always

1. Read `AGENTS.md`.
2. Read `IMPLEMENTATION_STATUS.json` and `IMPLEMENTATION_STATUS.md`.
3. Inspect the repository and verify the status file against actual code/tests.
4. Read `IMPLEMENTATION_PLAN.md`.
5. Read every file in `docs/`, including:
   - `05A_STATE_MACHINE_SPEC.md`
   - `06A_WEB_RESEARCH_SPEC.md`
6. Read `tasks/TASK_INDEX.md`.
7. Inspect `evals/` and `private_input/README.md`.
8. Inspect existing private_input files if available, but never commit them.
9. Build a concise internal dependency map and continue from the first unfinished milestone.

Do NOT ask the user to manually feed TASK-001, TASK-002, etc.
Use task files internally as acceptance criteria.

If `IMPLEMENTATION_STATUS.json` says a milestone is complete:
- verify it,
- do not reimplement it unless verification fails.

## Execution policy

- Implement milestone by milestone.
- Complete the smallest coherent vertical slice for each milestone.
- After every milestone, run its tests and the global smoke/regression suite.
- Update `IMPLEMENTATION_STATUS.json` after every milestone and before any planned stop.
- If interrupted, leave the current milestone `in_progress` with notes.
- Do not proceed with broken P0/P1 tests.
- Do not rewrite working unrelated code.
- Prefer the simplest implementation that preserves required behavior.

## Product behavior to preserve

The system automates the user's current GPT workflow:

JD / company
→ current company/job research
→ actual job output
→ evidence retrieval
→ Direct / Adjacent / No Evidence
→ Main Skill / Differentiator / Gap
→ application strategy
→ question message/claim
→ writing
→ fact / ownership / recruiter QA
→ minimal patch revision
→ final document
→ submission snapshot
→ interview handoff
→ outcome/postmortem later

Resume and cover letter share the same Career Truth Core and Opportunity analysis.

## State policy

`docs/05A_STATE_MACHINE_SPEC.md` is canonical for:
- workflow transitions,
- lock/edit behavior,
- stale propagation,
- conversational commands.

Never reconstruct workflow state from chat history alone.

## Company research policy

`docs/06A_WEB_RESEARCH_SPEC.md` is canonical.

The first runnable product must support manual/user-supplied JD mode.
If live web/search credentials are available, implement the live research adapter.
If not:
- implement the interface and fake/manual provider,
- keep the product runnable,
- document the credential/config required for live research,
- continue all other work.

Never pass raw external webpage instructions as privileged prompt instructions.

## LLM policy

Use LLMs for:
- interpretation
- semantic evidence selection
- strategy
- claim design
- writing
- recruiter review
- reverse interview

Use deterministic code for:
- workflow state
- permissions
- exact source/metric presence
- canonical truth resolution
- stale dependency propagation
- character counting
- versions
- hard validation

Do not implement a free-form autonomous multi-agent system.

## Jev policy

The first working system must NOT depend on Jev.

Implement a `DecisionModel` interface.
Use LLM structured output as primary.
Jev starts only as a shadow provider in its designated milestone.

## Eval policy

Do not block initial product implementation on creating 30–50 historical cases.

TASK-000 uses:
- the existing small smoke-regression set,
- deterministic hard-rule tests,
- production telemetry schema.

The system must log enough real usage to later build a larger production-derived evaluation set.

Later, when enough production corrections exist, compare:
- B0 strong LLM only
- B1 LLM + retrieval
- B2 strategy + writer
- B3 full workflow

## Private input policy

`private_input/` is optional local seed data.

Importer must:
- recurse through present supported files,
- work when some folders are empty,
- preserve provenance,
- remain idempotent,
- never commit private files.

## Completion

Continue through the implementation plan autonomously until:
- all required milestones are complete,
- all tests pass,
- local deployment works,
- end-to-end personal workflow works.

If an external credential/provider is unavailable:
- implement interface + mock/manual fallback,
- document required environment variables,
- continue non-blocked work.

At the end provide:
1. completed milestone checklist,
2. architecture summary,
3. commands to run locally,
4. required environment variables,
5. test results,
6. known limitations,
7. next recommended production experiment.

Begin or resume now.


## v2.2 final invariants

- `OpportunityBrief` contains company/job-side analysis only.
- Candidate fatal gaps, selection risks, assignment statement belong to `ApplicationBrief`.
- `SUBMISSION_FROZEN` is not `SUBMITTED`.
- Actual submission requires explicit confirmation.
- `InterviewHandoff` is a separate artifact derived from `SubmissionBundle`.
- Production telemetry tables are required from early implementation.
- Core Workbench UI is built alongside vertical slices, not deferred entirely to M14.
