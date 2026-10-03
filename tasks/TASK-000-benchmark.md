# TASK-000 — Smoke Regression + Production Telemetry

Prerequisite: TASK-001 infrastructure complete.

## Goal

Critical regression guardrails + real production feedback capture.

Do not block implementation on 30–50 historical cases.

## Implement

### Eval case schema
Load existing small historical set.

### Smoke runner
At minimum:
- canonical fact violation
- ownership overclaim
- unsupported metric
- claim-boundary violation
- stale/superseded source use

### Telemetry persistence
Implement DB models/repos for:
- `ArtifactFeedbackEvent`
- `DocumentRevisionEvent`

Record:
- stage
- artifact id/version
- ACCEPT/EDIT/REJECT/SKIP
- before/after
- edit type
- application/question ids
- latency/cost/provider where relevant

Generated docs:
- draft version
- final locked version
- edit distance/diff summary
- reviewer issues
- accepted reviewer suggestions

### Baseline interfaces
B0/B1/B2/B3 runner interfaces/placeholders.

Acceptance:
- smoke set runs
- hard-rule tests catch intentional violations
- telemetry write/read tests pass
- production events can later export into eval schema
