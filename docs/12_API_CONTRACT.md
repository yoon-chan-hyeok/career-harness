# API Contract — v2.2 FINAL

REST primary. MCP later wraps same application services.

Costly mutation endpoints should accept an idempotency key where practical.

## Career Truth
- GET /api/profile
- GET /api/projects
- GET /api/projects/{id}
- POST /api/sources/import
- POST /api/corrections
- GET /api/evidence/search?q=...

## Opportunity
- POST /api/opportunities
- POST /api/opportunities/{id}/research
- POST /api/opportunities/{id}/analyze
- GET /api/opportunities/{id}/brief
- GET /api/opportunities/{id}/evidence-pack
- PATCH /api/opportunities/{id}/evidence-map

## Application
- POST /api/applications
- GET /api/applications/{id}
- POST /api/applications/{id}/strategy
- POST /api/applications/{id}/approve-strategy
- POST /api/applications/{id}/questions/{qid}/brief
- PATCH /api/applications/{id}/questions/{qid}/brief
- POST /api/applications/{id}/questions/{qid}/approve
- POST /api/applications/{id}/questions/{qid}/generate
- POST /api/applications/{id}/questions/{qid}/review
- POST /api/applications/{id}/resume/generate

## Submission
- POST /api/applications/{id}/submission/freeze
  - creates immutable SubmissionBundle
  - state → SUBMISSION_FROZEN

- POST /api/applications/{id}/submission/confirm
  - explicit actual submission confirmation
  - state → SUBMITTED
  - sets submitted_at

- GET /api/applications/{id}/submission

## Interview
- POST /api/applications/{id}/interview-handoff
- GET /api/applications/{id}/interview-handoff

## Conversational patches
- POST /api/applications/{id}/commands

Request:
```json
{"text":"RAG 빼"}
```

Response:
```json
{
  "interpreted_action":"REMOVE_EVIDENCE",
  "patched_artifacts":[],
  "stale_artifacts":[],
  "message":""
}
```

## Outcome
- POST /api/applications/{id}/outcome
- POST /api/applications/{id}/postmortem

## Eval/trace
- POST /api/evals/run
- GET /api/evals/runs/{id}
- GET /api/traces/{run_id}
