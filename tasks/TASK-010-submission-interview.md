# TASK-010 — Submission Freeze + Interview Handoff

Read `docs/05A_STATE_MACHINE_SPEC.md`.

## Submission freeze

When application is READY_TO_FREEZE:
- create immutable SubmissionBundle,
- set state SUBMISSION_FROZEN,
- set frozen_at,
- do NOT set submitted_at.

SubmissionBundle includes:
- frozen opportunity/application versions
- final cover letters
- final resume
- ClaimLedger
- evidence/metrics/gaps

## Actual submission

Only explicit user/system confirmation such as "제출했다":
- transitions SUBMISSION_FROZEN → SUBMITTED
- sets submitted_at

Never infer submission from content lock/freeze.

## InterviewHandoff

Separate artifact derived from SubmissionBundle:
- claim defense
- ownership
- metric scope
- expected follow-ups
- fatal-gap answers
- 1/3/5 minute project explanations

May be regenerated without changing SubmissionBundle.

Acceptance:
- freeze != submitted
- InterviewHandoff separate from bundle
- handoff always points to exact frozen submission facts
