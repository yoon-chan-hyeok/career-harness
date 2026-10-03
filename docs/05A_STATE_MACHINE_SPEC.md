# State Machine Specification — v2.2 FINAL

This document is canonical for workflow state transitions.
If it conflicts with informal workflow prose, this document wins.

The system must never infer workflow transitions only from chat history.

---

## 1. Artifact statuses

- ACTIVE
- LOCKED
- STALE
- SUPERSEDED
- INVALID

A LOCKED artifact is immutable.
Editing creates a new version.

---

## 2. Application workspace states

```text
CREATED
  ↓
OPPORTUNITY_ANALYZING
  ↓
OPPORTUNITY_READY
  ↓
EVIDENCE_READY
  ↓
STRATEGY_PROPOSED
  ↓
WAITING_STRATEGY_APPROVAL   [Guided mode]
  ↓
STRATEGY_LOCKED
  ↓
COMPOSING
  ↓
REVIEWING
  ↓
READY_TO_FREEZE
  ↓
SUBMISSION_FROZEN
  ↓
SUBMITTED
  ↓
CLOSED
```

Exceptional:
- PARTIAL_COMPLETE
- NEED_USER_ACTION
- PROVIDER_UNAVAILABLE

### Transition rules

`CREATED → OPPORTUNITY_ANALYZING`
- analyze opportunity.

`OPPORTUNITY_ANALYZING → OPPORTUNITY_READY`
- requires valid OpportunityBrief.

`OPPORTUNITY_READY → EVIDENCE_READY`
- requires valid EvidencePack.

`EVIDENCE_READY → STRATEGY_PROPOSED`
- requires valid ApplicationBrief.

`STRATEGY_PROPOSED → WAITING_STRATEGY_APPROVAL`
- Guided mode.

`STRATEGY_PROPOSED → STRATEGY_LOCKED`
- Fast mode only when no escalation condition.

`WAITING_STRATEGY_APPROVAL → STRATEGY_LOCKED`
- explicit approval.

`STRATEGY_LOCKED → COMPOSING`
- cover letter and/or resume composition begins.

`COMPOSING → REVIEWING`
- at least one requested draft exists.

`REVIEWING → READY_TO_FREEZE`
- no blocking P0/P1 issue on requested documents.

`READY_TO_FREEZE → SUBMISSION_FROZEN`
- explicit freeze/lock action.
- creates immutable SubmissionBundle.
- does NOT mean the application was submitted.

`SUBMISSION_FROZEN → SUBMITTED`
- explicit user/system submission confirmation event only.
- must record submitted_at.
- never infer from draft completion or freeze alone.

`SUBMITTED → CLOSED`
- user closes application tracking or final outcome archived.

---

## 3. Question states

```text
NEW
 ↓
BRIEF_PROPOSED
 ↓
WAITING_CLAIM_APPROVAL   [Guided mode]
 ↓
BRIEF_LOCKED
 ↓
DRAFTED
 ↓
REVIEWED
 ↓
FINAL_READY
 ↓
FINAL_LOCKED
```

Additional:
- QA_FAILED
- STALE

Writer may run only from BRIEF_LOCKED.

---

## 4. Resume states

```text
NOT_REQUESTED
 ↓
BRIEF_READY
 ↓
CONTENT_DRAFTED
 ↓
REVIEWED
 ↓
FINAL_READY
 ↓
FINAL_LOCKED
```

Resume and cover letter progress independently after STRATEGY_LOCKED.

---

## 5. Submission and interview relationship

`SubmissionBundle`
- created at SUBMISSION_FROZEN,
- immutable,
- contains frozen cover letter/resume/claims/gaps.

`InterviewHandoff`
- separate downstream artifact,
- depends_on SubmissionBundle,
- may be regenerated,
- must not mutate the frozen submission snapshot.

---

## 6. Dependency invalidation

### Opportunity/JD/company research changed
new OpportunityBrief →
- EvidencePack STALE
- ApplicationBrief STALE
- QuestionBriefs STALE
- Drafts/Reviews STALE
- Resume STALE
- InterviewHandoff STALE

### Evidence classification changed
new EvidencePack →
- ApplicationBrief STALE
- affected question/resume outputs STALE

### Ownership changed
- dependent claims/docs STALE
- re-run ownership QA

### Metric changed
- dependent claims/docs STALE
- frozen submission remains historical immutable snapshot, not silently rewritten

### Writing/style preference changed
- truth artifacts stay current
- generated prose may be regenerated

---

## 7. Conversational commands

`ㄱㄱ`
- execute exactly one next valid workflow action.

`이걸로 가자`
- approve current proposal.

`잠가`
- lock current eligible artifact.
- if application is READY_TO_FREEZE, create SUBMISSION_FROZEN.
- does not set SUBMITTED.

`제출했다`
- if SUBMISSION_FROZEN exists, transition to SUBMITTED and set submitted_at.
- if no frozen bundle exists, request freeze/confirmation first.

`다시`
- regenerate current stage, stale downstream.

`이건 Adjacent`
- patch evidence relation, regenerate EvidencePack, stale dependents.

`RAG 빼`
- remove matching evidence from current brief, stale downstream prose.

`이건 내가 한 거 아님`
- ownership correction, stale dependent claims/docs.

`이 수치 틀림`
- metric conflict/invalidation, block affected locks until resolved.

---

## 8. Escalation conditions

Fast mode stops for:
- conflicting canonical fact,
- essential output with NO_EVIDENCE,
- ambiguous ownership for key claim,
- unsupported/high-risk metric,
- materially competing positionings,
- company motivation claim based on inference only,
- stale/invalid dependency.

---

## 9. Resumption

Runtime application state is stored in DB.
Codex implementation progress uses `IMPLEMENTATION_STATUS.json`.
These are separate systems.
