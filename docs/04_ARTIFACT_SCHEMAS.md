# Canonical Artifact Schemas — v2.2 FINAL

Keep generated artifacts few and broad.

---

## 1. OpportunityBrief

**Scope:** company/job-side analysis only.  
It must not contain candidate-specific fatal gaps or assignment statements that require EvidencePack.

```json
{
  "actual_outputs": [],
  "base_profession": "",
  "specialty": "",
  "tools": [],
  "main_skills": [],
  "differentiators": [],
  "hiring_context": "",
  "company_facts": [],
  "company_inferences": [],
  "selection_process_signals": []
}
```

Notes:
- `company_facts` must be source-backed.
- `company_inferences` must be explicitly labeled inference.
- candidate fit/gaps belong downstream.

---

## 2. EvidencePack

**Scope:** relationship between current opportunity outputs and candidate evidence.

```json
{
  "items": [
    {
      "evidence_id": "",
      "job_output_id": "",
      "classification": "DIRECT",
      "evidence_strength": "STRONG",
      "ownership_strength": "STRONG",
      "ownership": {},
      "metrics": [],
      "claim_boundaries": [],
      "verification_status": "VERIFIED",
      "source_ids": []
    }
  ],
  "uncovered_outputs": []
}
```

Classification:
- DIRECT
- ADJACENT
- NO_EVIDENCE

Ordinal strength:
- STRONG
- MODERATE
- LIMITED
- NONE

---

## 3. ApplicationBrief

**Scope:** candidate-specific strategy built only after `OpportunityBrief + EvidencePack`.

```json
{
  "positioning": "",
  "base_profession_identity": "",
  "main_skill_message": "",
  "differentiator_message": "",
  "fatal_gaps": [],
  "selection_risks": [],
  "fatal_gap_strategy": "",
  "assignment_statement": "",
  "do_not_position_as": [],
  "question_portfolio": []
}
```

`assignment_statement` answers:

> "입사 후 실제로 이 지원자에게 맡길 수 있는 일은 무엇인가?"

It may not be created before EvidencePack exists.

---

## 4. QuestionBrief

```json
{
  "question_id": "",
  "question_type": "",
  "evaluation_intent": "",
  "primary_message": "",
  "supporting_claims": [],
  "evidence_ids": [],
  "decision": "",
  "insight": "",
  "job_relevance": "",
  "forbidden_claims": [],
  "style_projection": {}
}
```

---

## 5. ResumeBrief

```json
{
  "target_role": "",
  "top_capabilities": [],
  "project_order": [],
  "selected_evidence_ids": [],
  "section_budget": {},
  "bullet_intents": []
}
```

---

## 6. ClaimLedger

Atomic claims extracted from generated text.

```json
{
  "claims": [
    {
      "claim_id": "",
      "text": "",
      "type": "FACT|METRIC|OWNERSHIP|INTERPRETATION",
      "evidence_ids": [],
      "metric_ids": [],
      "support": "SUPPORTED",
      "ownership_ok": true
    }
  ]
}
```

---

## 7. SubmissionBundle

**Scope:** immutable snapshot of the exact application content prepared for/used in submission.

```json
{
  "opportunity_version": "",
  "application_brief_version": "",
  "resume_version": "",
  "cover_letter_answers": [],
  "claim_ledger": {},
  "known_gaps": [],
  "frozen_at": "",
  "submitted_at": null
}
```

Important:
- `frozen_at` means content is locked/frozen.
- `submitted_at` is null until explicit submission confirmation.
- locking/finalizing content does NOT imply actual submission.

---

## 8. InterviewHandoff

Derived from a frozen or submitted `SubmissionBundle`.

```json
{
  "submission_bundle_id": "",
  "claim_defense": [],
  "ownership_notes": [],
  "metric_scope_notes": [],
  "expected_followups": [],
  "fatal_gap_answers": [],
  "project_explanations": {
    "one_minute": [],
    "three_minute": [],
    "five_minute": []
  }
}
```

InterviewHandoff is a separate artifact and can be regenerated without mutating SubmissionBundle.

---

## Artifact rules

- Store `depends_on`.
- On upstream change, mark downstream STALE.
- LOCKED artifact is immutable; editing creates a new version.
- `SUBMISSION_FROZEN` and `SUBMITTED` are different application states.
