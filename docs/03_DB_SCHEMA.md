# Database Schema — v2.2 FINAL

Use PostgreSQL + pgvector.

All user-owned tables include `user_id`.

## Core tables

- users
- sources
- career_facts
- projects
- evidences
- decision_episodes
- metrics
- ownership_records
- claim_boundaries
- writing_rules
- expression_records
- capability_records

## Opportunity/application tables

- opportunities
- company_research_results
- opportunity_job_outputs
- opportunity_evidence_maps
- application_workspaces
- application_questions
- artifacts
- artifact_dependencies
- draft_versions
- review_issues
- submission_snapshots
- interview_handoff_records
- selection_outcomes
- postmortem_hypotheses
- correction_records
- prompt_runs

## Production telemetry

- artifact_feedback_events
- document_revision_events

These tables are required from the first usable production slice.

`artifact_feedback_events` records:
- stage
- proposal artifact/version
- ACCEPT/EDIT/REJECT/SKIP
- before/after payload
- edit type
- timestamps

`document_revision_events` records:
- document version transitions
- edit distance/diff summary
- reviewer issue linkage

They are the source for later production-derived eval cases.

## Vector columns

Embeddings on:
- evidences
- decision_episodes
- expression_records
- optionally company research snippets

Vector similarity never decides canonical truth.

## Important indexes

- `(user_id, key, status)` career_facts
- `(user_id, verification_status)` evidences
- GIN FTS searchable text
- pgvector index when size justifies
- `(workspace_id, state)` application_questions
- artifact dependency index
- `(application_id, stage, created_at)` artifact_feedback_events
- `(application_id, document_type, created_at)` document_revision_events

## Submission semantics

`submission_snapshots` fields include:
- frozen_at NOT NULL
- submitted_at NULLABLE

Creating/finalizing a submission snapshot does not set submitted_at.

## Deletion

Deleting a source:
1. invalidate unsupported dependent fact/evidence,
2. propagate STALE to generated dependents,
3. preserve historical immutable submission snapshots but mark deleted-source provenance as unavailable where legally/technically appropriate,
4. never silently keep unsupported canonical truth.

## Migration policy

All schema changes use Alembic.
